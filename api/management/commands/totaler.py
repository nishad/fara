import json
import datetime


from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from FaraData.models import Contact, Registrant, MetaData, Payment, Contribution, Location
from fara_feed.models import Document

class Command(BaseCommand):
	help = "Creates data for the 2013 totals page."
	can_import_settings = True

	def handle(self, *args, **options):
		total_registrants()
		location_api()


def total_registrants():
	registrants = Registrant.objects.all()
	results = []
	for r in registrants:
		reg_id = r.reg_id
		registrant ={}
		if Document.objects.filter(processed=True,reg_id=reg_id,doc_type__in=['Supplemental','Amendment'],stamp_date__range=(datetime.date(2013,1,1), datetime.date.today())).exists():
			doc_list = []
			registrant["reg_name"] = r.reg_name
			registrant['reg_id'] = r.reg_id
			for doc in Document.objects.filter(processed=True,reg_id=reg_id,doc_type__in=['Supplemental','Amendment'],stamp_date__range=(datetime.date(2013,1,1), datetime.date.today())):
				doc_list.append(doc.url)
			
			docs_2013 = []
			s13 = 0
			for doc in doc_list:
				md = MetaData.objects.get(link=doc)
				end_date = md.end_date
				if end_date != None:
					if datetime.date(2013,1,1) <= md.end_date <= datetime.date(2013,12,31):
						docs_2013.append(doc)
						if "Supplemental" in doc:
							s13 = s13 + 1
						if "Registration" in doc:
							s13 = s13 + 1

			if s13 == 2:
				complete_records13 = True
				registrant['complete_records13'] = True
			else:
				registrant['complete_records13'] = False

			if Payment.objects.filter(link__in=docs_2013):
				payments2013 = Payment.objects.filter(link__in=docs_2013).aggregate(total_pay=Sum('amount'))
				payments2013 = float(payments2013['total_pay'])
				registrant['payments2013'] = payments2013

			if Contact.objects.filter(registrant=reg_id,recipient__agency__in=["Congress", "House", "Senate"], meta_data__end_date__range=(datetime.date(2013,1,1), datetime.date.today()) ).exists():
				registrant['federal_lobbying'] = True
			else:
				registrant['federal_lobbying'] = False
				
			if Contact.objects.filter(registrant=reg_id,recipient__agency="U.S. Department of State", meta_data__end_date__range=(datetime.date(2013,1,1), datetime.date.today()) ).exists():
				registrant['state_dept_lobbying'] = True
			else:
				registrant['state_dept_lobbying'] = False
				
			if Contact.objects.filter(registrant=reg_id,recipient__agency="Media", meta_data__end_date__range=(datetime.date(2013,1,1), datetime.date.today()) ).exists():
				registrant['pr'] = True
			else:
				registrant['pr'] = False

			if Contribution.objects.filter(registrant=reg_id, meta_data__end_date__range=(datetime.date(2013,1,1), datetime.date.today())).exists():
				registrant['contribution'] = True
			else:
				registrant['contribution'] = False
				
			if s13 != 0:
				results.append(registrant)
	
	# save to file
	with open("api/computations/reg13.json", 'w') as f:
		results = json.dumps({'results':results}, separators=(',',':'))
		f.write(results)
	

def location_api():
	locations = Location.objects.all()
	results = {}
	results["000"] = []
	for l in locations:
		if l.country_code:
			if results.has_key(l.country_code):
				results[l.country_code].append({'name':l.location, 'id': l.id, 'region':l.region})
			else:
				results[l.country_code] = [{'name':l.location, 'id': l.id, 'region':l.region}]
		else:
			results["000"].append({'name':l.location, 'id': l.id, 'region':l.region})

	with open("api/computations/map.json", 'w') as f:
		results = json.dumps({'results':results}, separators=(',',':'))
		f.write(results)
