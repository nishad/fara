import datetime
import re
import sys
import time
import urllib
import urllib2
import string
import argparse
import os
import codecs
import logging

from bs4 import BeautifulSoup
from PyPDF2 import PdfFileReader
from elasticsearch import Elasticsearch

from django.core.management.base import BaseCommand, CommandError
from django.core.files.storage import default_storage
from django.conf import settings 

from fara_feed.models import Document
from FaraData.models import MetaData, Registrant

es = Elasticsearch(**settings.ES_CONFIG)

logging.basicConfig()
logger = logging.getLogger(__name__)

documents = []
fara_url = 'https://efile.fara.gov/pls/apex/wwv_flow.accept'

class Command(BaseCommand):
    help = "Crawls the DOJ's FARA site looking for new documents."
    can_import_settings = True
    args = 'date_range'

    def handle(self, *args, **options):

        if args:
            for date_input in args:
                dates = date_input.split(':')
                start_date = datetime.datetime.strptime(dates[0], "%Y-%m-%d")
                end_date = datetime.datetime.strptime(dates[1], "%Y-%m-%d")
        else:
            start_date = datetime.date.today() - datetime.timedelta(days=25)
            end_date = datetime.date.today()

        # this_filename = os.path.abspath(__file__)
        # this_parent_dir = os.path.dirname(this_filename) + '/../..'
        # outdir = os.path.join(this_parent_dir, "output")
        # if not os.path.exists(outdir):
        #     os.mkdir(outdir)
        # print "files will be saved to %s" % (outdir)
        
        doj_url = 'https://efile.fara.gov/pls/apex/f?p=125:10:::NO::P10_DOCTYPE:ALL'
        search_html = urllib2.urlopen(doj_url).read()
        search_page = BeautifulSoup(search_html)
        form = search_page.find("form", {"id":"wwvFlowForm"})
        data = []
        for input in form.findAll('input'):
            if input.has_attr('name'):
                if input['name'] not in ('p_t01', 'p_t02', 'p_t06', 'p_t07', 'p_request'):
                    data.append((input['name'], input['value']))
        
        data += [('p_t01', 'ALL'),
                 ('p_t02', 'ALL'),
                 ('p_t06', start_date.strftime('%m/%d/%Y')),
                 ('p_t07', end_date.strftime('%m/%d/%Y')),
                 ('p_request', 'SEARCH'),
        ]
       
        url = 'https://efile.fara.gov/pls/apex/wwv_flow.accept'
        req = urllib2.Request(url, data=urllib.urlencode(data))
        
        page = urllib2.urlopen(req).read()
        page = BeautifulSoup(page)
        parse_and_save(page)
        next_url_realitive = page.find("a", {"class":"t14pagination"})

        while next_url_realitive != None:
            url_end = next_url_realitive['href']
            next_url = 'https://efile.fara.gov/pls/apex/' + url_end
            req = urllib2.Request(next_url)
            
            page = urllib2.urlopen(req).read()
            page = BeautifulSoup(page)
            parse_and_save(page)
            next_url_realitive = page.find("a", {"class":"t14pagination"})

    
def add_file(url):
    if url[:25] != "http://www.fara.gov/docs/":
        message = 'bad link ' + url
        logger.error(message)
        print message
    else:
        file_name = "pdfs/" + url[25:]
        if not default_storage.exists(file_name):
            try:
                url = str(url)
                u = urllib2.urlopen(url)
                text = u.read()
                localFile = default_storage.open(file_name, 'w')
                # writing pdf to amazon
                localFile.write(text)
                # closing amazon file
                localFile.close()

                # adding to document model
                doc = Document.objects.get(url=url)
                doc.uploaded = True
                doc.save()

                return text
            
            except:
                message = 'bad upload ' + url
                logger.error(message)
                return None

        else:
            doc = Document.objects.get(url=url)
            if doc.uploaded != True:  
                doc.uploaded = True
                doc.save()
            return None


def save_text(url_info, text):
    url = url_info['url']

    if text == None:
        amazon_file_name = "pdfs/" + url[25:]
        pdf = default_storage.open(amazon_file_name, 'rb')
        pdf_file = PdfFileReader(pdf)
        pages = pdf_file.getNumPages()
        count = 0
        text = ''
        while count < pages:
            pg = pdf_file.getPage(count)
            pgtxt = pg.extractText()
            count = count + 1
            text = text + pgtxt

    document = Document.objects.get(url=url)
    doc_id = document.id

    
    #saving to elastic search
    try:
        doc = {
                'type': url_info['doc_type'],
                'date': url_info['stamp_date'],
                'registrant': url_info['reg_name'],
                'reg_id': url_info['reg_id'],
                'doc_id': doc_id, 
                'link': url,
                'text': text,
        }
        res = es.index(index="foreign", doc_type='fara_files', id=doc_id, body=doc)
    except:
        message = 'bad pdf no es upload for %s ' % (url)
        logger.error(message)
    
    # saving to disk
    file_name = "data/form_text/" + url[25:-4] + ".txt"
    with open(file_name, 'w') as txt_file:
        txt_file.write(text.encode('utf8'))


def add_document(url_info):
    url = str(url_info['url']).strip()
    if not Document.objects.filter(url = url).exists():
        document = Document(url = url,
            reg_id = url_info['reg_id'],
            doc_type = url_info['doc_type'],
            stamp_date = url_info['stamp_date'],
        )
        document.save()

        
    if not MetaData.objects.filter(link= url).exists():
        document = Document.objects.get(url = url)
        md = MetaData(link = url,
                        upload_date = datetime.date.today(),
                        reviewed = False,
                        processed = False,
                        is_amendment = False,
                        form = document.id,
            )

    reg_id = url_info['reg_id']
    if not Registrant.objects.filter(reg_id=reg_id):
        reg = Registrant (reg_id=reg_id,
            reg_name = url_info['reg_name']
            )
        reg.save()

    doc = {
                'name': url_info['reg_name'],
                'reg_id': reg_id
    }

    res = es.index(index="foreign", doc_type='registrant', id=reg_id, body=doc)



def parse_and_save(page):
    filings = page.find("table", {"class" : "t14Standard"})
    new_fara_docs = []

    for l in filings.find_all("tr"):
        url = l.find('a')['href']
        if url[:4] == "http":
            stamp_date = l.find('td',{"headers" : "STAMPED/RECEIVEDDATE"})
            stamp_date = stamp_date.text
            try:
                stamp_date_obj = datetime.datetime.strptime(stamp_date, "%m/%d/%Y")
            except:
                # just in case there is a problem with the form
                stamp_date = re.findall(r'\d{8}', url)
                stamp_date = stamp_date[0]
                stamp_date_obj = datetime.datetime.strptime(stamp_date, "%Y%m%d")
            
            date_string = stamp_date_obj.strftime('%Y-%m-%d')
            reg_name = l.find('td',{"headers" : "REGISTRANTNAME"})
            reg_name = reg_name.text    
            reg_id = re.sub('-','', url[25:29])
            reg_id = re.sub('S','', reg_id)
            reg_id = re.sub('L','', reg_id)
            re.findall(r'href="(.*?)"', url)
            info = re.findall( r'-(.*?)-', url)

            if info[0] == 'Amendment':
                doc_type = 'Amendment'

            elif info[0] == 'Short':
                doc_type = 'Short Form'

            elif info[0] == 'Exhibit':
                if "AB" in url:
                    doc_type = 'Exhibit AB'  
                if "C" in url:
                    doc_type = 'Exhibit C'    
                if "D" in url:
                    doc_type = 'Exhibit D'

            elif info[0] == 'Conflict':
                doc_type = 'Conflict Provision'

            elif info[0] == 'Registration':
                doc_type = 'Registration'

            elif info[0] == 'Supplemental':
                doc_type = 'Supplemental' 

            else:
                message = "Can't identify form-- %s " % (url)
                doc_type = 'unknown'
                logger.error(message)


            url_info= {'url':url,'reg_name':reg_name,  'reg_id':reg_id, 'doc_type':doc_type, 'stamp_date':date_string}
            documents.append(url_info)
            #saving
            add_document(url_info)
            text = add_file(url)
            save_text(url_info, text)
            new_fara_docs.append(url_info)
            




      



