#!/usr/bin/env python
# Code (c) Dan Neidle, Tax Policy Associates Ltd, 2024. Based on an original idea and coding by M
# html creation code largely created by chatGPT 4o
# licensed under the GNU General Public License, version 2

# note that Companies House throttling means this takes about 90 minutes to run.

import os
import time
import requests
import json
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

import logzero
from logzero import logger

import companies_house_secrets
"""
companies_house_secrets.py should have the following format:

    api_key = "<your api key>" 
    companies_house_secrets.upload_directory = None [if you don't want to upload the html to a website] or scp destination, if you do

instructions for obtaining a Companies House api key are at https://developer-specs.company-information.service.gov.uk/guides/authorisation

"""

GENERATE_PLC_LIST = True   # Normally True. Set to False for debugging, and will load last generated list, saving a bit of time
ANALYSE_PLC_LIST = True    # Normally True. Set to False for debugging, and will then load last generated list, saving a LOT of time

COMPANIES_HOUSE_API_URL = 'https://api.company-information.service.gov.uk/'
CH_ADVANCED_SEARCH = 'advanced-search/companies'
CH_GET_PROFILE = '/company/'

# how many results to return. The Companies House limit is 5,000. Fortunately there are only about 4,500 active plcs
MAX_SEARCH_SIZE = 5000

# for when we are throttled
API_RETRY_WAIT = 30
MAX_API_RETRIES = 50

PLC_LIST_FILE = 'active_plcs.json'
LATE_COMPANIES_LIST_FILE = 'late_plcs.json'
HTML_EXPORT_FILE = 'late_plc_table.html'

def get_active_plcs():
    companies = []

    url = f'{COMPANIES_HOUSE_API_URL}{CH_ADVANCED_SEARCH}?company_status=active&company_type=plc&size={MAX_SEARCH_SIZE}'
    
    response = requests.get(url, auth=(companies_house_secrets.api_key, ''))
    
    if response.status_code != 200:
        logger.info(f"Error: {response.status_code} - {response.text}")
        return
    
    data = response.json()
    companies.extend(data.get('items', []))
    logger.info(f"Downloaded {len(companies)}...")
            
    return companies


def save_to_file(companies, filename):
    with open(filename, 'w') as file:
        json.dump(companies, file, indent=4)
        

def load_from_file(filename):
    try:
        with open(filename, 'r') as file:
            companies = json.load(file)
            return companies
    except FileNotFoundError:
        logger.info(f"Error: The file '{filename}' was not found.")
        return []
    except json.JSONDecodeError:
        logger.info(f"Error: The file '{filename}' is not a valid JSON file.")
        return []
        

def get_company_profile(company_number):
    url = f'{COMPANIES_HOUSE_API_URL}{CH_GET_PROFILE}{company_number}'
    
    retries = 0
    while retries < MAX_API_RETRIES:
        response = requests.get(url, auth=(companies_house_secrets.api_key, ''))
        
        if response.status_code == 200:
            if "accounts" in response.text:
                return response.json()
            else:
                logger.info(f"Error: Unexpected response format for {company_number} - {response.status_code} - {response.text}")
                exit(1)
        
        elif response.status_code == 502 or response.status_code == 429:
            retries += 1
            logger.info(f"{response.status_code} Error: throttled, retrying in 60 seconds... ({retries}/{MAX_API_RETRIES})")
            time.sleep(API_RETRY_WAIT)
            
        else:
            logger.info(f"Error: {response.status_code} - {response.text}")
            exit(1)
    
    logger.info(f"Failed to retrieve company profile for {company_number} after {MAX_API_RETRIES} attempts.")
    exit(1)

def find_days_late(due_date: str) -> int:
    # Convert the due date string into a datetime object
    due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
    
    # Get today's date
    today = datetime.today().date()
    
    # Calculate the difference in days
    days_late = (today - due_date).days
    
    return days_late

def get_late_plcs(list_of_active_plcs):
    
    result = []
    for i, plc in enumerate(list_of_active_plcs):
        
        logger.info(f'{i + 1}/{len(list_of_active_plcs)}: {plc["company_name"]} - {plc["company_number"]}')
        profile = get_company_profile(plc["company_number"])
        
        if "next_accounts" not in profile["accounts"]:
            logger.info(f"Inactive company")
            continue
            
        
        # logger.info(profile)
        # logger.info("")
        
        accounting = profile["accounts"]["next_accounts"]
        if accounting["overdue"]:
           # logger.info("late!") 
           
           data = {}
           data["name"] = plc["company_name"]
           data["link"] = f'https://find-and-update.company-information.service.gov.uk/company/{plc["company_number"]}'
           data["due_date"] = accounting["due_on"]
           data["days_late"] = find_days_late(accounting["due_on"])
           
           result.append(data)
           logger.info(data)
        else:
            pass
            # logger.info("Accounts filed on time!")
            
        
    return result


def create_html(late_plcs, number_of_active_plcs):

    # Set up Jinja2 environment and load template
    env = Environment(loader=FileSystemLoader(searchpath='.'))
    
    # Define the template string with Bootstrap and DataTables
    template_string = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://cdn.datatables.net/1.13.4/css/jquery.dataTables.min.css">
        <link rel="stylesheet" href="https://cdn.datatables.net/1.13.4/css/dataTables.bootstrap5.min.css">
        <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/5.3.0/css/bootstrap.min.css">
        <title>Late Filings</title>
        <style>
            .container {
                margin-top: 20px;
            }
            table.dataTable thead {
                background-color: #007bff;
                color: white;
            }
        </style>
    </head>
    <body>
        
        <div class="container">
            <p>Total late PLCs: {{ number_of_late_plcs }} (out of {{ number_of_active_plcs }} total PLCs). Data last updated: {{ current_date }}.</p>
            <table id="latePlcsTable" class="table table-striped table-bordered">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Due Date</th>
                        <th>Days Late</th>
                    </tr>
                </thead>
                <tbody>
                    {% for company in companies %}
                    <tr>
                        <td><a href="{{ company.link }}" target="_blank">{{ company.name }}</a></td>
                        <td>{{ company.due_date }}</td>
                        <td>{{ company.days_late }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script>
        <script src="https://cdn.datatables.net/1.13.4/js/dataTables.bootstrap5.min.js"></script>
        <script>
            $(document).ready(function() {
                $('#latePlcsTable').DataTable({
                    "order": [[ 2, "asc" ]],
                    "paging": false,
                    "searching": false,
                    "autoWidth": true,        
                    "columnDefs": [
                        { 
                            "targets": 0,  // Target the first column
                            "width": "1%", // Let it auto-size but prevent it from taking too much space
                            "render": function (data, type, full, meta) {
                                return '<div style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' + data + '</div>';
                            }
                        }
                    ]
                });
            });
        </script>
    </body>
    </html>
    """

    # Create a Jinja2 template from the string
    template = env.from_string(template_string)
    
    current_date = datetime.now().strftime('%-d %B %Y, %-I:%M%p').replace('AM', 'am').replace('PM', 'pm')

    # Render the template with the sorted list
    html_output = template.render(companies=late_plcs, current_date=current_date, number_of_late_plcs=len(late_plcs), number_of_active_plcs=number_of_active_plcs)

    # Write the rendered HTML to the output file
    with open(HTML_EXPORT_FILE, 'w') as f:
        f.write(html_output)



if __name__ == "__main__":
    
    logzero.logfile("late-accounts.log", maxBytes=1e6, backupCount=4)
    

    if GENERATE_PLC_LIST:
        logger.info("Reading list of all PLCs from Companies House")
        active_plcs = get_active_plcs()
        save_to_file(active_plcs, PLC_LIST_FILE)
        
    else:  
        logger.info("Loading pregenerated list of all PLCs")
        active_plcs = load_from_file(PLC_LIST_FILE)
    
    
    if ANALYSE_PLC_LIST:
        logger.info("Analysing all PLCs to find late accounts")
        late_plcs = get_late_plcs(active_plcs)
        save_to_file(late_plcs, LATE_COMPANIES_LIST_FILE)
    
    else:
        logger.info("Loading pregenerated list of all late accounts")
        late_plcs = load_from_file(LATE_COMPANIES_LIST_FILE)
    
    logger.info(f"Checking through {len(active_plcs)} active PLCs")  
    
    logger.info(f"Found {len(late_plcs)} late PLCs")  
    create_html(late_plcs, len(active_plcs))
    
    if companies_house_secrets.upload_directory:
        logger.info("Uploading to wordpress site")
        os.system(f'scp {HTML_EXPORT_FILE} {companies_house_secrets.upload_directory}')
        
    logger.info("All done!")
    