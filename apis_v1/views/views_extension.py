# apis_v1/views/views_extension.py
# Brought to you by We Vote. Be good.
# -*- coding: UTF-8 -*-
import datetime
import json
import os
import subprocess
import urllib.request

import boto3
from django.http import HttpResponse

import wevote_functions.admin
from config.base import get_environment_variable
from exception.models import handle_exception
from wevote_functions.functions import positive_value_exists, get_voter_device_id

AWS_ACCESS_KEY_ID = get_environment_variable("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = get_environment_variable("AWS_SECRET_ACCESS_KEY")
AWS_REGION_NAME = get_environment_variable("AWS_REGION_NAME")
AWS_STORAGE_BUCKET_NAME = "wevote-temporary"
AWS_STORAGE_SERVICE = "s3"

logger = wevote_functions.admin.get_logger(__name__)

WE_VOTE_SERVER_ROOT_URL = get_environment_variable("WE_VOTE_SERVER_ROOT_URL")


def pdf_to_html_retrieve_view(request):  # pdfToHtmlRetrieve
    """
    return a URL to a s3 file that contains the html rough equivalent of the PDF
    :param request:
    :return:
    """
    voter_device_id = get_voter_device_id(request)  # We standardize how we take in the voter_device_id
    pdf_url = request.GET.get('pdf_url', '')
    return_version = request.GET.get('version', False)

    if not positive_value_exists(pdf_url) and not return_version:
        status = 'PDF_URL_MISSING'
        json_data = {
            'status':                   status,
            'success':                  False,
            's3_url_for_html':          '',
        }
        return HttpResponse(json.dumps(json_data), content_type='application/json')

    try:
        json_data = process_pdf_to_html(pdf_url, return_version)
    except Exception as e:
        logger.error('pdf2htmlEX call to process_pdf_to_html from pdf_to_html_retrieve_view e: ' + str(e))


    return HttpResponse(json.dumps(json_data), content_type='application/json')


def process_pdf_to_html(pdf_url, return_version):
    output = 'exception before output'
    logger.error('pdf2htmlEX entry to process_pdf_to_html:' + pdf_url + '   ' + str(return_version))
    if return_version:
        try:
            process = subprocess.run(['/pdf2htmlEX', '-v', 'True'])
            output = process.stdout
            logger.error('pdf2htmlEX version:', output)
        except Exception as e:
            logger.error('pdf2htmlEX version exception: ' + str(e))

        json_data = {
            'status': 'PDF2HTMLEX_VERSION',
            'success': True,
            'output_from_subprocess': output,
            's3_url_for_html': '',
        }
        return json_data

    file_name, headers = urllib.request.urlretrieve(pdf_url)
    pdf_name = os.path.basename(pdf_url)
    dirname, basename = os.path.split(file_name)
    temp_file_name = file_name.replace(basename, pdf_name)
    try:
        os.remove(temp_file_name)
        html_name = temp_file_name.replace('.pdf', '.html')
        os.remove(html_name)
    except Exception as e2:
        logger.error('pdf2htmlEX version exception e2: ' + str(e2))
        pass

    os.rename(file_name, temp_file_name)
    logger.error('pdf2htmlEX temp_file_name: ', temp_file_name)
    # https://github.com/pdf2htmlEX/pdf2htmlEX  !DO NOT USE the abandoned coolwanglu original branch!
    # https://github.com/pdf2htmlEX/pdf2htmlEX/wiki/Command-Line-Options
    # In December 2020, we installed a docker image in AWS/EC2: https://hub.docker.com/r/cardboardci/pdf2htmlex
    # pdf2htmlEX -zoom 1.3 Cook-18-Primary-Web.pdf

    # March 2023:
    # docker run -ti --rm --mount src="$(pwd)",target=/pdf,type=bind pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64 --zoom 1.3 .//2022-CADEM-General-Endorsements.pdf

    # Test cases:
    # https://www.iuoe399.org/media/filer_public/45/77/457700c9-dd70-4cfc-be49-a81cb3fba0a6/2020_lu399_primary_endorsement.pdf
    # http://www.local150.org/wp-content/uploads/2018/02/Cook-18-Primary-Web.pdf
    # http://www.sddemocrats.org/sites/sdcdp/files/pdf/Endorsements_Flyer_P2020b.pdf
    # https://crpa.org/wp-content/uploads/2020-CA-Primary-Candidate-Final.pdf

    try:
        process = subprocess.run(['pdf2htmlEX', '--dest-dir', dirname, temp_file_name])
        output = process.stdout
        logger.error('pdf2htmlEX output: ' + str(output))
    except Exception as e3:
        logger.error('pdf2htmlEX subprocess.run exception: ' + str(e3))
    temp_file_name = temp_file_name.replace('.pdf', '.html')

    try:
        insert_pdf_filename_in_tmp_file(temp_file_name, pdf_url)
    except Exception as e4:
        logger.error('pdf2htmlEX insert_pdf_filename_in_tmp_file: ' + str(e4))

    s3_url_for_html = store_temporary_html_file_to_aws(temp_file_name)
    logger.error("pdf2htmlEX stored temp html file: ", temp_file_name, s3_url_for_html)

    status = 'PDF_URL_RETURNED'
    json_data = {
        'status': status,
        'success': True,
        'output_from_subprocess': output,
        's3_url_for_html': s3_url_for_html,
    }
    return json_data


def store_temporary_html_file_to_aws(temp_file_name):
    """
    Upload temporary_html_file directly to AWS
    :param temp_file_name:
    :return:
    """
    s3_html_url = ""
    try:
        head, tail = os.path.split(temp_file_name)
        date_in_a_year = datetime.datetime.now() + + datetime.timedelta(days=365)
        session = boto3.session.Session(region_name=AWS_REGION_NAME,
                                        aws_access_key_id=AWS_ACCESS_KEY_ID,
                                        aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
        s3 = session.resource(AWS_STORAGE_SERVICE)
        s3.Bucket(AWS_STORAGE_BUCKET_NAME).upload_file(
            temp_file_name, tail, ExtraArgs={'Expires': date_in_a_year, 'ContentType': 'text/html'})
        s3_html_url = "https://{bucket_name}.s3.amazonaws.com/{file_location}" \
                      "".format(bucket_name=AWS_STORAGE_BUCKET_NAME,
                                file_location=tail)
    except Exception as e:
        print(e)
        exception_message = "store_temp_html_file_to_aws failed"
        handle_exception(e, logger=logger, exception_message=exception_message)

    return s3_html_url


def insert_pdf_filename_in_tmp_file(temp_file, pdf_url):
    f = open(temp_file, "r")
    contents = f.readlines()
    f.close()

    value = "<input type=\"hidden\" name=\"pdfFileName\" value=\"{pdf_url}\" />\n".format(pdf_url=pdf_url)

    # insert the hidden input as the first line of the body -- containgingthe original URL for the PDF
    offset = contents.index("<body>\n") + 1
    contents.insert(offset, value)

    f = open(temp_file, "w")
    contents = "".join(contents)
    f.write(contents)
    f.close()
