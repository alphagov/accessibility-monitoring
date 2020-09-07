import os, json, datetime, time, sys, getopt, ssl
import re
from sqlalchemy import create_engine, Column, Integer, String, Boolean, MetaData, Table, and_, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import DateTime
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSON

import requests
import urllib3
from urllib.parse import urlparse

import logging
logger = logging.getLogger()
logger.setLevel(logging.WARNING)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

totalTests = 0
successfulTests = 0
skippedTests = 0
failedTests = 0
tic=0
toc=0
destination_url = ""


def axeRunner(dom2test):
    axerunnerResult = requests.get('https://axerunner.london.cloudapps.digital', params={'targetURL':dom2test})
    if axerunnerResult.status_code==200:
        return axerunnerResult.json()
    else:
        errorDict = axerunnerResult.json()
        return errorDict



def parseResult(jsonIn):
    # parse into python dict:
    resultsDict = json.loads(jsonIn)
    return resultsDict

def saveResult(domain_name, resultsDict):
    global toc
    toc = time.perf_counter()
    if "error" in resultsDict:
        result = session.execute(
            test_header.insert(), {"test_timestamp": datetime.datetime.now(), "url": "", "domain_name": domain_name, "axe_version": "", "test_environment": "", "time_taken": toc-tic, "test_succeeded": False, "further_info": resultsDict["error"]["message"]})

        test_id = result.inserted_primary_key[0]
        session.commit()
    else :
        #logger.info(json.dumps(resultsDict["url"], indent=3), toc-tic, "seconds")

        result = session.execute(
            test_header.insert(), {"test_timestamp": resultsDict["timestamp"], "url": resultsDict["url"], "domain_name": domain_name, "axe_version": resultsDict["testEngine"]["version"], "test_environment": resultsDict["testEnvironment"], "time_taken": toc-tic, "test_succeeded": True})

        test_id = result.inserted_primary_key[0]
        session.commit()

        #record data. We're doing this the long way as we want the results to say "pass" not "passes" and "violation" not "violations" etc and it's just less faff TBH
        #record violations
        count=0
        for testItem in resultsDict["violations"]:
            count+=1
            result = session.execute(
                test_data.insert(), {"test_id": test_id, "rule_name": testItem["id"], "test_status": "violation", "nodes": testItem["nodes"]})
        session.commit()

        #record passes
        count=0
        for testItem in resultsDict["passes"]:
            count+=1
            result = session.execute(
                test_data.insert(), {"test_id": test_id, "rule_name": testItem["id"], "test_status": "pass", "nodes": testItem["nodes"]})
        session.commit()

        #record inapplicable
        count=0
        for testItem in resultsDict["inapplicable"]:
            count+=1
            result = session.execute(
                test_data.insert(), {"test_id": test_id, "rule_name": testItem["id"], "test_status": "inapplicable", "nodes": testItem["nodes"]})
        session.commit()

        #record incomplete
        count=0
        for testItem in resultsDict["incomplete"]:
            count+=1
            result = session.execute(
                test_data.insert(), {"test_id": test_id, "rule_name": testItem["id"], "test_status": "incomplete", "nodes": testItem["nodes"]})
        session.commit()

"""
    saveStatus - record http(s) status in domain_register table (only temporary while we use domain_register)
"""
def saveStatus(domain_name, ssl, status_code):
    if ssl:
        result = session.execute(
            "UPDATE pubsecweb.domain_register SET https_status_code=:status_code, last_updated=NOW() WHERE domain_name=:domain_name",
            {"status_code":status_code, "domain_name":domain_name})
    else:
        result = session.execute(
            "UPDATE pubsecweb.domain_register SET http_status_code=:status_code, last_updated=NOW() WHERE domain_name=:domain_name",
            {"status_code": status_code, "domain_name": domain_name})
    session.commit()

"""
    saveInfo - record url and title + description in website register
"""
def saveInfo(url, title, description, original_domain):
    result = session.execute(
        "INSERT INTO pubsecweb.website_register (url, htmlhead_title, htmlmeta_description, original_domain) VALUES (:url, :htmlhead_title, :htmlmeta_description, :original_domain) " \
        "ON CONFLICT (url)"
        "DO UPDATE SET htmlhead_title = :htmlhead_title, htmlmeta_description = :htmlmeta_description, last_updated=NOW();",
        {"url":url, "htmlhead_title":title, "htmlmeta_description":description, "original_domain":original_domain})
    session.commit()

"""
    doAxeTest - run axe on the domain, parse the results, save 'em
"""
def doAxeTest(site):
    global successfulTests, failedTests, domain_under_test
    axeResult = 0
    resultsDict = {"error":{"message": "Axe returned no result"}}

    axeResult = axeRunner(site)

    if axeResult:
        resultsDict = axeResult
        if "error" in resultsDict:
            logger.info(resultsDict["error"]["message"])
            failedTests+=1
            toc = time.perf_counter()
            saveResult(domain_under_test, resultsDict)
            return(0)
        else:
            # don't bother recording it if it just led to an error page (NB this depends on axe using chrome)
            if resultsDict["url"]=="chrome-error://chromewebdata/":
                failedTests+=1
                toc = time.perf_counter()
                saveResult(site, resultsDict)
                return(0)
            saveResult(domain_under_test, resultsDict)
            successfulTests+=1

    else:
        logger.info("No result returned")
        # we've already tried it with and without www so give up.
        failedTests+=1
        toc = time.perf_counter()
        saveResult(domain_under_test, resultsDict)


"""
    checkSiteExists - check the http response of the site; follow redirect(s recursively)
"""
def checkSiteExists(site, ssl):
    global domain_under_test, destination_url
    global successfulTests, failedTests
    r = {}
    timeout = 30

    logger.info("checkSiteExists(" + site + ", " + ("SSL=True)" if ssl else "SSL=False)"))


    # see if it responds and check its http header
    try:
        # fudge the headers. Some sites reject the request if they don't recognise the user agent
        headers = {'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36'}
        if ssl:
            r = requests.head("https://" + site, allow_redirects=False, timeout=timeout, headers=headers)
        else:
            r = requests.head("http://" + site, allow_redirects=False, timeout=timeout, headers=headers)

    except requests.exceptions.RequestException as e:
        logger.info(site + " failed to fetch header: ConnectionError=")
        logger.info(e)
        # try it with dubs on it
        if site[0:4] != 'www.':
            return checkSiteExists('www.' + site, ssl)
        else:
            return ""

    if r:
        # save the status_code in domains table (uses raw domain (site.gov.uk) rather than full URL)
        saveStatus(domain_under_test, ssl, r.status_code)

        url = r.url
        if r.status_code <400:
            # it's either good to go or a redirect.
            logger.debug("returning " + url)
            return url

        else:
            # >400. Do nothing as the status code will already have been recorded. There's nothing more to do.
            logger.info("website fail")
            logger.info(r.headers)
            return ""
    else:
        return ""

"""
    fetchSiteInfo - retrieve title and description from html
"""
def fetchSiteInfo(url):
    timeout = 30
    htmlhead_title = ""
    htmlmeta_description = ""

    # we can't rely on the target having correctly configured SSL (a surprising number aren't),
    # so we have an option to disable verification - set this to False
    # Normally this would be unwise, but we're only fetching 2 specific html elements
    verify_ssl = True

    try:
        # fudge the headers. Some sites reject the request if they don't recognise the user agent
        headers = {
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36'}

        r = requests.get(url, allow_redirects=True, verify=verify_ssl, timeout=timeout, headers=headers)



        if r.status_code<300:
            # see if we can get some info. NB use ([\s\S]*?) instead of (?s)(.*) as the latter is greedy and matches the entire page
            # title
            htmlheadTitleDict = re.findall('<title>([\s\S]*?)</title>', r.text)
            if len(htmlheadTitleDict)>0:
                htmlhead_title = htmlheadTitleDict[0].strip()
            # description
            htmlmetaDescriptionDict = re.findall('<meta name="description" content="([\s\S]*?)"', r.text)
            if len(htmlmetaDescriptionDict)>0:
                htmlmeta_description = htmlmetaDescriptionDict[0].strip()

            # save the stuff. But strip off default port numbers from URLs first.
            destination_url = re.sub(":80", "", r.url)
            destination_url = re.sub(":443", "", r.url)

            saveInfo(destination_url, htmlhead_title, htmlmeta_description, domain_under_test)
            logger.info("Resolved destination = " + destination_url)

            return True
        else:
            return False

    except requests.exceptions.RequestException as e:
        logger.info(url + " failed to fetch page: ConnectionError=")
        logger.info(e)


"""
*******************************************
doTheLoop - cycle through all sites to test
*******************************************
"""
def doTheLoop():
    global totalTests, tic, toc, successfulTests, failedTests, skippedTests
    global domain_under_test

    logger.info("Selecting data...")
    # pick a url at random
    # in the long term, the urls to test will be picked from a specific list, but for now we're testing ALL THE THINGS
    ###query = session.query(domain_register).filter(or_(domain_register.c.http_status_code=='200', domain_register.c.https_status_code=='200')).order_by(func.random())
    query = session.query(domain_register).order_by(func.random())
    rows=query.all()
    totalRows=query.count()
    for row in rows:
        print("Testing " + row.domain_name)
        domain_under_test = row.domain_name
        destination_url = ""

        # check to see when we last tested this url
        oneYearAgo = datetime.datetime.now() - datetime.timedelta(days=365)
        #oneYearAgo = datetime.datetime.now() - datetime.timedelta(days=1) # <-- temporary while we populate the website_register table with contents of domain_register
        testedRows = session.query(test_header).filter(and_(test_header.c.test_timestamp>oneYearAgo, test_header.c.domain_name==row.domain_name)).count()
        if testedRows==0:
            # we've not done this one within the last year so carry on
            tic = time.perf_counter()
            totalTests+=1
            print()
            print("****************************")
            print("Test number " , totalTests, " of ", totalRows, ": ", row.domain_name)
            print("****************************")

            surl = checkSiteExists(row.domain_name, True)

            nurl = checkSiteExists(row.domain_name, False)

            # favour SSl
            url_to_test = surl if surl != "" else nurl

            if url_to_test != "":
                logger.debug("go test " + url_to_test)
                fetchSiteInfo(url_to_test)
                doAxeTest(url_to_test)
            else:
                skippedTests +=1
                logger.debug("dead site")

            print(f"Time taken: {toc - tic:0.4f} seconds ({tic:0.4f}, {toc:0.4f})")
            print("Successful tests: ", successfulTests)
            print("Skipped tests: ", skippedTests)
            print("Failed tests: ", failedTests)
            print("****************************")
            print()
        else:
            print("Already tested.")

    print(".")
    print("****************************")
    print("Total tests: " , totalTests)
    print("****************************")


"""
******************
script entry point
******************
"""
# set to database credentials/host
# taken from local environment variable in the format postgresql+psycopg2://localuser:localuser@localhost/a11ymon
CONNECTION_URI = os.getenv("DATABASE_URL")

domain_under_test = ""

print("Connecting to database...")
engine = create_engine(CONNECTION_URI)

Session = sessionmaker(bind=engine)
session = Session()

Base = declarative_base()

# Create a MetaData instance
metadata = MetaData()

# reflect db schema to MetaData
metadata.reflect(bind=engine, schema='pubsecweb')
metadata.reflect(bind=engine, schema='a11ymon')

#AxeRules = metadata.tables['a11ymon.axe_rules']
test_header = metadata.tables['a11ymon.testresult_axe_header']
test_data = metadata.tables['a11ymon.testresult_axe_data']
domain_register = metadata.tables['pubsecweb.domain_register']
website_register = metadata.tables['pubsecweb.website_register']

# need to override the reflected definition of these as it fails to recognise the auto-increment :(
test_header = Table('testresult_axe_header', metadata,
    Column('test_id',Integer, primary_key=True, autoincrement=True),
    Column('test_timestamp',DateTime(timezone=True), default=func.now()),
    Column('url', String),
    Column('domain_name',String),
    Column('axe_version',String),
    Column('test_succeeded',Boolean),
    schema='a11ymon',
    extend_existing=True
)
test_data = Table('testresult_axe_data', metadata,
    Column('test_data_id',Integer, primary_key=True, autoincrement=True),
    Column('test_id', Integer),
    Column('rule_name', String),
    Column('test_status',String),
    Column('nodes',JSON),
    schema='a11ymon',
    extend_existing=True
)

domain_register = Table('domain_register', metadata,
    Column('domain_id',Integer, primary_key=True, autoincrement=True),
    Column('domain_name', String),
    Column('http_status_code', String),
    Column('http_status_code',String),
    Column('data_source',String),
    schema='pubsecweb',
    extend_existing=True
)

website_register = Table('website_register', metadata,
    Column('website_id',Integer, primary_key=True, autoincrement=True),
    Column('url', String),
    Column('htmlhead_title', String),
    Column('htmlmeta_description',String),
    schema='pubsecweb',
    extend_existing=True
)



def main(argv):
    global domain_under_test
    singleDomain = ''

    try:
      opts, args = getopt.getopt(argv,"hd:",["singleDomain="])
    except getopt.GetoptError:
      print ('axerunner.py -d <domain_name>')
      sys.exit(2)
    for opt, arg in opts:
     if opt == '-h':
          print ('axerunner.py -d <domain_name>')
          sys.exit()
     elif opt in ("-d", "--singleDomain"):
         singleDomain = arg
         logger.info ('single url to test is ' + singleDomain)

    if singleDomain:
       domain_under_test = singleDomain

       surl = checkSiteExists(singleDomain, True)
       logger.debug("surl=" + surl)

       nurl = checkSiteExists(singleDomain, False)
       logger.debug("nurl=" + nurl)

       url_to_test = surl if surl!="" else nurl

       if url_to_test != "":
           logger.debug("go test " + url_to_test)
           fetchSiteInfo(url_to_test)
           doAxeTest(url_to_test)
       else:
           logger.debug("dead site")

    else:
       doTheLoop()


if __name__ == "__main__":
   main(sys.argv[1:])
