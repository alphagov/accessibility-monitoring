import os, time, sys, getopt
import re
import requests

from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, func
import psycopg2

import logging

logger = logging.getLogger()
logger.setLevel(logging.WARNING)

logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

totalSlurps = 0
successfulSlurps = 0
skippedSlurps = 0
failedSlurps = 0
tic = 0
toc = 0
destination_url = ""


"""
    saveInfo - record url and title + description in website register
"""
def saveInfo(website_id, html_content):
    result = session.execute(
        "UPDATE website_content SET home_page_content = :html_content, last_updated=NOW() WHERE website_id = :website_id;",
        {"html_content": html_content, "website_id": website_id})
    session.commit()


"""
    checkSiteExists - check the http response of the site; follow redirect(s recursively)
"""
def checkSiteExists(site, ssl):
    global url_to_slurp, destination_url
    global successfulSlurps, failedSlurps
    r = {}
    timeout = 5

    logger.info("checkSiteExists(" + site + ", " + ("SSL=True)" if ssl else "SSL=False)"))

    # see if it responds and check its http header
    try:
        # fudge the headers. Some sites reject the request if they don't recognise the user agent
        headers = {
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36'}
        if ssl:
            r = requests.head("https://" + site, allow_redirects=True, timeout=timeout, headers=headers)
        else:
            r = requests.head("http://" + site, allow_redirects=True, timeout=timeout, headers=headers)

        if r.status_code:
            logger.debug(r.status_code)
        else:
            logger.debug("no result")
    except Exception as ex:
        template = "An exception of type {0} occurred. Arguments:\n{1!r}"
        message = template.format(type(ex).__name__, ex.args)
        logger.info(message)
        return ""

    if r.status_code:
        url = r.url
        if r.status_code < 400:
            # it's either good to go or a redirect.
            logger.debug("returning " + url)
            return url

        else:
            # >400. Do nothing as the status code will already have been recorded. There's nothing more to do.
            logger.info("website fail")
            logger.info(r.headers)
            return ""
    else:
        # save NOH (=no header) in domains table (uses raw domain (site.gov.uk) rather than full URL)
        logger.debug("no result")
        return ""


"""
    fetchPage - retrieve html
"""
def fetchPage(website_id, url):
    timeout = 30

    # we can't rely on the target having correctly configured SSL (a surprising number aren't),
    # so we have an option to disable verification - set this to False
    # Normally this would be unwise, but we're only fetching 2 specific html elements
    verify_ssl = True

    try:
        # fudge the headers. Some sites reject the request if they don't recognise the user agent
        headers = {
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36'}

        r = requests.get(url, allow_redirects=True, verify=verify_ssl, timeout=timeout, headers=headers)

        if r.status_code < 300:
            saveInfo(website_id, r.text)
            return True
        else:
            return False

    except requests.exceptions.RequestException as e:
        logger.info(url + " failed to fetch page: ConnectionError=")
        logger.info(e)


"""
**********************************************
doTheLoop - cycle through all sites to process
**********************************************
"""


def doTheLoop():
    global totalSlurps, tic, toc, successfulSlurps, failedSlurps, skippedSlurps
    global url_to_slurp

    logger.info("Selecting data...")
    # pick a url at random
    ## for testing single site => query = session.query(websites).filter_by(website_id=13044).order_by(func.random())
    query = session.query(websites).filter(websites.last_updated == None).order_by(func.random())
    rows = query.all()
    totalRows = query.count()
    for row in rows:
        url_to_slurp = row.home_page_url
        print("Testing " + url_to_slurp)

        tic = time.perf_counter()
        totalSlurps += 1
        print()
        print("****************************")
        print("Slurp number ", totalSlurps, " of ", totalRows, ": ", url_to_slurp)
        print("****************************")

        # check the site exists with & without SSL
        surl = checkSiteExists(url_to_slurp, True)
        nurl = checkSiteExists(url_to_slurp, False)

        # # favour SSl
        url_to_test = surl if surl != "" else nurl

        if url_to_test != "":
            logger.debug("go test " + url_to_test)
            if (fetchPage(row.website_id, url_to_test)):
                successfulSlurps += 1
            else:
                failedSlurps += 1
        else:
            skippedSlurps += 1
            logger.debug("dead site")

        toc = time.perf_counter()
        print(f"Time taken: {toc - tic:0.4f} seconds ({tic:0.4f}, {toc:0.4f})")

        print("Successful/skipped/failed slurps: ", successfulSlurps, "/", skippedSlurps, "/", failedSlurps)
        print("****************************")
        print()

    print(".")
    print("****************************")
    print("Total tests: ", totalSlurps)
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



def main(argv):
    global url_to_slurp
    singleDomain = ''

    try:
        opts, args = getopt.getopt(argv, "hd:", ["singleDomain="])
    except getopt.GetoptError:
        print('slurp.py -d <domain_name>')
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print('slurp.py -d <domain_name>')
            sys.exit()
        elif opt in ("-d", "--singleDomain"):
            singleDomain = arg
            logger.info('single url to retrieve is ' + singleDomain)

    if singleDomain:
        url_to_slurp = singleDomain

        surl = checkSiteExists(singleDomain, True)
        logger.debug("surl=" + surl)

        nurl = checkSiteExists(singleDomain, False)
        logger.debug("nurl=" + nurl)

        url_to_fetch = surl if surl != "" else nurl

        if url_to_fetch != "":
            logger.debug("go fetch " + url_to_fetch)
            fetchPage(14886, url_to_fetch)
        else:
            logger.debug("dead site")

    else:
        doTheLoop()


if __name__ == "__main__":
    main(sys.argv[1:])


