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

import logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.WARNING)
ch.setFormatter(formatter)
logger.addHandler(ch)

totalTests = 0
successfulTests = 0
failedTests = 0
tic=0
toc=0

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
        result = session.execute(domain_register.update().where(domain_register.c.domain_name==domain_name).values(https_status_code=status_code))
    else:
        result = session.execute(domain_register.update().where(domain_register.c.domain_name==domain_name).values(http_status_code=status_code))
    session.commit()
    logger.debug(result.last_updated_params())

"""
    saveInfo - record url and title + description in website register
"""
def saveInfo(url, title, description, original_domain):
    result = session.execute(
        "INSERT INTO pubsecdomains.website_register (url, htmlhead_title, htmlmeta_description, original_domain) VALUES (:url, :htmlhead_title, :htmlmeta_description, :original_domain) " \
        "ON CONFLICT (url)" \
        "DO UPDATE SET htmlhead_title = :htmlhead_title, htmlmeta_description = :htmlmeta_description;",
        {"url":url, "htmlhead_title":title, "htmlmeta_description":description, "original_domain":original_domain})
    session.commit()

"""
    doAxeTest - run axe on the domain, parse the results, save 'em
"""
def doAxeTest(site, addSomeDubs):
    global successfulTests, failedTests
    axeResult = 0
    resultsDict = {"error":{"message": "Axe returned no result"}}

    if addSomeDubs:
        # retrying the site with www. prepended
        site = "www." + site

    axeResult = axeRunner(site)

    if axeResult:
        resultsDict = axeResult
        if "error" in resultsDict:
            logger.info(resultsDict["error"]["message"])
            failedTests+=1
            toc = time.perf_counter()
            saveResult(site, resultsDict)
            return(0)
        else:
            # don't bother recording it if it just led to an error page (NB this depends on axe using chrome)
            if resultsDict["url"]=="chrome-error://chromewebdata/":
                failedTests+=1
                toc = time.perf_counter()
                saveResult(site, resultsDict)
                return(0)
            saveResult(site, resultsDict)
            successfulTests+=1
    else:
        logger.info("No result returned")
        if addSomeDubs:
            # we've already tried it with and without www so give up.
            failedTests+=1
            toc = time.perf_counter()
            saveResult(site, resultsDict)
            ## todo: handle invalid http response.
        else:
            # do the test again but with www. prepended to the url
            doAxeTest(site, True)

"""
    checkSiteExists - check the http response of the site; follow redirect(s recursively)
"""
def checkSiteExists(site, ssl):
    global domain_under_test, destination_url
    destination_url = ""
    http_response_valid = 0
    htmlhead_title = ""
    htmlmeta_description = ""


    logging.info("checkSiteExists(" + site + ", " + ("SSL=True)" if ssl else "SSL=False)"))

    # first we'll see if it responds and check its http header
    try:
        # fudge the headers. Some sites reject the request if they don't recognise the user agent
        headers = {'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.125 Safari/537.36'}
        if ssl:
            # we can't rely on the target having correctly configured SSL, so we'll disable verification.
            # Normally this would be dangerous, but we're only fetching the response status and 2 specific html elements
            urllib3.disable_warnings()
            r = requests.get("https://" + site, allow_redirects=False, verify=False, timeout=15, headers=headers)
        else:
            r = requests.get("http://" + site, allow_redirects=False, timeout=15, headers=headers)

        logger.debug(r.status_code)
        logger.debug(r.headers)

        # save the status_code before we do any redirecting shenanigans
        # We can sometimes get a different status from domain.com and www.domain.com, so only record the former
        if site[0:4] != 'www.':
            saveStatus(domain_under_test, ssl, r.status_code)

        if r.status_code > 300 and r.status_code < 400:
            ## handle redirect
            redirect_url = r.headers['location']

            # check if it's just a directory - starts with / or /.
            if redirect_url[0] == '/':
                # just make sure that there's not a / on the end of the site already...
                if site[-1] == '/': site = site[0:-1]
                redirect_url = site + redirect_url
                logger.debug("A redirecting to " + redirect_url)
                checkSiteExists(redirect_url, ssl)
            elif  redirect_url[0] == '.':
                redirect_url = site + redirect_url[1:]
                logger.debug("B redirecting to " + redirect_url)
                checkSiteExists(redirect_url, ssl)
            else:
                # if it's the same url but as https:// then we don't need to record anything new - it's the same domain/folder.
                if redirect_url == "https://" + site or redirect_url == "https://" + site + "/":
                    # same url but https
                    redirect_url = redirect_url[8:]
                    logger.debug("C redirecting to " + redirect_url)
                    checkSiteExists(redirect_url,True)
                else:
                    # check the new site that we've been redirected to
                    if "https://" in redirect_url:
                        redirect_url = redirect_url[8:]
                        logger.debug("D redirecting to " + redirect_url)
                        checkSiteExists(redirect_url,True)
                    else:
                        redirect_url = redirect_url[7:]
                        logger.debug("E redirecting to " + redirect_url)
                        checkSiteExists(redirect_url, False)

        elif r.status_code < 300:
            http_response_valid = True

        else:
            # >400. Do nothing as the status code will already have been recorded. There's nothing more to do.
            logger.info("website fail")
            logger.info(r.headers)


    except requests.exceptions.RequestException as e:
        logger.warning(site + " failed to connect: ConnectionError=")
        logger.warning(e)
        # try it with dubs on it
        if site[0:4] != 'www.':
            checkSiteExists('www.' + site, ssl)

    if http_response_valid:
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
        doAxeTest(destination_url, False)



"""
*******************************************
doTheLoop - cycle through all sites to test
*******************************************
"""
def doTheLoop():
    global totalTests, tic, toc
    global domain_under_test

    logger.info("Selecting data...")
    # pick a url at random
    # in the long term, the urls to test will be picked from a specific list, but for now we're testing ALL THE THINGS
    ###query = session.query(domain_register).filter(or_(domain_register.c.http_status_code=='200', domain_register.c.https_status_code=='200')).order_by(func.random())
    query = session.query(domain_register).order_by(func.random())
    rows=query.all()
    totalRows=query.count()
    for row in rows:
        print(row.domain_name)
        # see if it's alive...
        # check to see when we last tested this url
        oneYearAgo = datetime.datetime.now() - datetime.timedelta(days=365)
        testedRows = session.query(test_header).filter(and_(test_header.c.test_timestamp>oneYearAgo, test_header.c.domain_name==row.domain_name)).count()
        if testedRows==0:
            # we've not done this one within the last year so carry on
            tic = time.perf_counter()
            totalTests+=1
            domain_under_test = row.domain_name
            print()
            print("****************************")
            print("Test number " , totalTests, " of ", totalRows, ": ", row.domain_name)
            print("****************************")
            domain_under_test = row.domain_name
            checkSiteExists(row.domain_name, False)
            checkSiteExists(row.domain_name, True)
            print(f"Time taken: {toc - tic:0.4f} seconds ({tic:0.4f}, {toc:0.4f})")
            print("Successful tests: ", successfulTests)
            print("Failed tests: ", failedTests)
            print("****************************")
            print()

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
metadata.reflect(bind=engine, schema='pubsecdomains')
metadata.reflect(bind=engine, schema='a11ymon')

#AxeRules = metadata.tables['a11ymon.axe_rules']
test_header = metadata.tables['a11ymon.testresult_axe_header']
test_data = metadata.tables['a11ymon.testresult_axe_data']
domain_register = metadata.tables['pubsecdomains.domain_register']
website_register = metadata.tables['pubsecdomains.website_register']

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
    schema='pubsecdomains',
    extend_existing=True
)

website_register = Table('website_register', metadata,
    Column('website_id',Integer, primary_key=True, autoincrement=True),
    Column('url', String),
    Column('htmlhead_title', String),
    Column('htmlmeta_description',String),
    schema='pubsecdomains',
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
         print ('single url to test is ', singleDomain)

    if singleDomain:
       domain_under_test = singleDomain
       checkSiteExists(singleDomain, False)
       checkSiteExists(singleDomain, True)
    else:
       doTheLoop()


if __name__ == "__main__":
   main(sys.argv[1:])
