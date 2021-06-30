import os, time, sys, getopt
from bs4 import BeautifulSoup

from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, func

import logging

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

totalSites = 0


"""
**********************************************
doTheLoop - cycle through all sites to process
**********************************************
"""


def doTheLoop():
    global current_website_id, totalSites

    logger.info("Selecting data...")
    # pick a url at random
    ## for testing single site => query = session.query(websites).filter_by(website_id=13044).order_by(func.random())
    query = session.query(websites).filter(websites.last_updated == None).order_by(func.random())
    rows = query.all()
    totalRows = query.count()
    for row in rows:
        current_website_id = row.home_page_url
        print("Testing " + current_website_id)

        tic = time.perf_counter()
        totalSites += 1
        print()
        print("****************************")
        slurps = totalSites
        print("Site number ", slurps, " of ", totalRows, ": ", current_website_id)
        print("****************************")
        print()

    print(".")
    print("****************************")
    print("Total tests: ", totalSites)
    print("****************************")


"""
******************
script entry point
******************
"""
# set to database credentials/host
# taken from local environment variable in the format postgresql+psycopg2://localuser:localuser@localhost/a11ymon
CONNECTION_URI = os.getenv("DATABASE_URL")
# need to fudge this for now as VCAP_SERVICES has the URI as postgres:... instead of postgresql:
if(CONNECTION_URI[:9] == "postgres:"):
    fudged_connection_uri = "postgresql" + CONNECTION_URI[8:]
else:
    fudged_connection_uri = CONNECTION_URI

print(fudged_connection_uri)

print("Connecting to database...")
engine = create_engine(fudged_connection_uri, connect_args={'options': '-csearch_path=analytics'})

Base = automap_base()

# reflect the tables
Base.prepare(engine, reflect=True)

# mapped classes are now created with names by default
# matching that of the table name.
websites = Base.classes.website_content

session = Session(engine)

##########
# Set up process flags
do_cleanup = False


def cleanup(website_id):
    # fetch raw text
    logger.debug("cleaning " + str(current_website_id))
    query=session.query(websites).filter(websites.website_id == website_id)
    raw_text = query.one().home_page_raw
    soup = BeautifulSoup(raw_text, 'html.parser')
    print(soup.title.string)
    # print(soup.get_text())
    

def doStuff(current_website_id):
    global do_cleanup
    logger.debug("doing stuff with " + str(current_website_id))
    if (do_cleanup):
        cleanup(current_website_id)



def main(argv):
    global current_website_id
    global do_cleanup
    singleSite = ''

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hs:c", ["singleSite="])
    except getopt.GetoptError:
        print('error in command line. Usage: catter.py -s <url>')
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print('catter.py -s <url>')
            sys.exit()
        if opt in ("-s", "--singleSite"):
            singleSite = arg
            logger.info('single url to retrieve is ' + singleSite)
        if opt in ("-c", "--cleanup"):
            do_cleanup = True


    if singleSite:
        query = session.query(websites).filter(websites.home_page_url == singleSite)
        current_website_id = query.one().website_id
        # do the thing...
        doStuff(current_website_id)
    else:
        doTheLoop()


if __name__ == "__main__":
    main(sys.argv[1:])


