"""

Copyright 2016, Institute for Systems Biology

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""

"""
Helper methods for fetching, curating, and managing cohort metadata
"""

import json
import collections
import csv
import sys
import random
import string
import time
from time import sleep
import logging
import json
import traceback
import copy
import urllib
import re
import MySQLdb
import warnings

from django.utils import formats
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.core.urlresolvers import reverse
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.conf import settings
from django.db.models import Count, Sum
import django

from django.http import StreamingHttpResponse
from django.core import serializers
from google.appengine.api import urlfetch
from allauth.socialaccount.models import SocialToken, SocialAccount
from django.contrib.auth.models import User as Django_User

from models import Cohort, Patients, Samples, Cohort_Perms, Source, Filters, Cohort_Comments
from workbooks.models import Workbook, Worksheet, Worksheet_plot
from projects.models import Project, Study, User_Feature_Counts, User_Feature_Definitions, User_Data_Tables
from visualizations.models import Plot_Cohorts, Plot
from bq_data_access.cohort_bigquery import BigQueryCohortSupport
from uuid import uuid4
from accounts.models import NIH_User

from api.api_helpers import *

BQ_ATTEMPT_MAX = 10

debug = settings.DEBUG # RO global for this file
urlfetch.set_default_fetch_deadline(60)

MAX_FILE_LIST_ENTRIES = settings.MAX_FILE_LIST_REQUEST
MAX_SEL_FILES = settings.MAX_FILES_IGV
BQ_SERVICE = None

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", "No data - zero rows fetched, selected, or processed")

METADATA_SHORTLIST = {
    'list': []
}

# Get a set of random characters of 'length'
def make_id(length):
    return ''.join(random.sample(string.ascii_lowercase, length))

# Database connection - does not check for AppEngine
def get_sql_connection():
    database = settings.DATABASES['default']
    try:
        connect_options = {
            'host': database['HOST'],
            'db': database['NAME'],
            'user': database['USER'],
            'passwd': database['PASSWORD']
        }

        if 'OPTIONS' in database and 'ssl' in database['OPTIONS']:
            connect_options['ssl'] = database['OPTIONS']['ssl']

        db = MySQLdb.connect(**connect_options)

        return db

    except Exception as e:
        logger.error("[ERROR] Exception in get_sql_connection(): " + str(sys.exc_info()[0]))
        if db and db.open: db.close()


def fetch_metadata_shortlist():
    try:
        cursor = None
        db = get_sql_connection()
        if not METADATA_SHORTLIST['list'] or len(METADATA_SHORTLIST['list']) <= 0:
            cursor = db.cursor()
            cursor.execute("SELECT COUNT(TABLE_NAME) FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_NAME = 'metadata_shortlist';")
            # Only try to fetch the values if the view exists
            if cursor.fetchall()[0][0] > 0:
                cursor.execute("SELECT attribute FROM metadata_shortlist;")
                METADATA_SHORTLIST['list'] = []
                for row in cursor.fetchall():
                    METADATA_SHORTLIST['list'].append(row[0])
            else:
                # Otherwise just warn
                logger.warn("[WARNING] View metadata_shortlist was not found!")

        return METADATA_SHORTLIST['list']
    except Exception as e:
        logger.error(traceback.format_exc())
    finally:
        if cursor: cursor.close()
        if db and db.open: db.close()


def get_metadata_value_set():
    values = {}
    db = get_sql_connection()

    try:
        cursor = db.cursor()
        cursor.callproc('get_metadata_values')

        values[cursor.description[0][0]] = {}
        for row in cursor.fetchall():
            values[cursor.description[0][0]][str(row[0])] = 0

        while (cursor.nextset() and cursor.description is not None):
            values[cursor.description[0][0]] = {}
            for row in cursor.fetchall():
                values[cursor.description[0][0]][str(row[0])] = 0

        return values

    except Exception as e:
        logger.error(traceback.format_exc())
    finally:
        if cursor: cursor.close()
        if db and db.open: db.close()


"""
BigQuery methods
"""

def submit_bigquery_job(bq_service, project_id, query_body, batch=False):

    job_data = {
        'jobReference': {
            'projectId': project_id,
            'job_id': str(uuid4())
        },
        'configuration': {
            'query': {
                'query': query_body,
                'priority': 'BATCH' if batch else 'INTERACTIVE'
            }
        }
    }

    return bq_service.jobs().insert(
        projectId=project_id,
        body=job_data).execute(num_retries=5)


def is_bigquery_job_finished(bq_service, project_id, job_id):

    job = bq_service.jobs().get(projectId=project_id,
                             jobId=job_id).execute()

    return job['status']['state'] == 'DONE'


def get_bq_job_results(bq_service, job_reference):

    result = []
    page_token = None

    while True:
        page = bq_service.jobs().getQueryResults(
            pageToken=page_token,
            **job_reference).execute(num_retries=2)

        if int(page['totalRows']) == 0:
            break

        rows = page['rows']
        result.extend(rows)

        page_token = page.get('pageToken')
        if not page_token:
            break

    return result


def data_availability_sort(key, value, attr_details):
    if key == 'has_Illumina_DNASeq':
        attr_details['DNA_sequencing'] = sorted(value, key=lambda k: int(k['count']), reverse=True)
    if key == 'has_SNP6':
        attr_details['SNP_CN'] = sorted(value, key=lambda k: int(k['count']), reverse=True)
    if key == 'has_RPPA':
        attr_details['Protein'] = sorted(value, key=lambda k: int(k['count']), reverse=True)

    if key == 'has_27k':
        count = [v['count'] for v in value if v['value'] == 'True']
        attr_details['DNA_methylation'].append({
            'value': '27k',
            'count': count[0] if count.__len__() > 0 else 0
        })
    if key == 'has_450k':
        count = [v['count'] for v in value if v['value'] == 'True']
        attr_details['DNA_methylation'].append({
            'value': '450k',
            'count': count[0] if count.__len__() > 0 else 0
        })
    if key == 'has_HiSeq_miRnaSeq':
        count = [v['count'] for v in value if v['value'] == 'True']
        attr_details['miRNA_sequencing'].append({
            'value': 'Illumina HiSeq',
            'count': count[0] if count.__len__() > 0 else 0
        })
    if key == 'has_GA_miRNASeq':
        count = [v['count'] for v in value if v['value'] == 'True']
        attr_details['miRNA_sequencing'].append({
            'value': 'Illumina GA',
            'count': count[0] if count.__len__() > 0 else 0
        })
    if key == 'has_UNC_HiSeq_RNASeq':
        count = [v['count'] for v in value if v['value'] == 'True']
        attr_details['RNA_sequencing'].append({
            'value': 'UNC Illumina HiSeq',
            'count': count[0] if count.__len__() > 0 else 0
        })
    if key == 'has_UNC_GA_RNASeq':
        count = [v['count'] for v in value if v['value'] == 'True']
        attr_details['RNA_sequencing'].append({
            'value': 'UNC Illumina GA',
            'count': count[0] if count.__len__() > 0 else 0
        })
    if key == 'has_BCGSC_HiSeq_RNASeq':
        count = [v['count'] for v in value if v['value'] == 'True']
        attr_details['RNA_sequencing'].append({
            'value': 'BCGSC Illumina HiSeq',
            'count': count[0] if count.__len__() > 0 else 0
        })
    if key == 'has_BCGSC_GA_RNASeq':
        count = [v['count'] for v in value if v['value'] == 'True']
        attr_details['RNA_sequencing'].append({
            'value': 'BCGSC Illumina GA',
            'count': count[0] if count.__len__() > 0 else 0
        })