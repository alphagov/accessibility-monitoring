import os, json, datetime, time, sys, getopt, ssl
import re
from sqlalchemy import create_engine, Column, Integer, String, Boolean, MetaData, Table, and_, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import DateTime
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSON

import requests

totalTests = 0
successfulTests = 0
failedTests = 0
tic=0
toc=0

def axeRunner(dom2test):
    print("testing ", dom2test)
    axerunnerResult = requests.get('https://axerunner.london.cloudapps.digital', params={'targetURL':'http://' + dom2test})
    if axerunnerResult.status_code==200:
        return axerunnerResult.json()
    else:
        print (axerunnerResult)
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
        print(json.dumps(resultsDict["url"], indent=3), toc-tic, "seconds")

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

    if addSomeDubs:
        # retrying the site with www. prepended
        site = "www." + site

    axeResult = axeRunner(site)

    if axeResult:
        # print(axeResult)
        #resultsDict = ast.literal_eval(axeResult)
        resultsDict = axeResult
        print(len(resultsDict))
        if "error" in resultsDict:
            #print (json.dumps(resultsDict,  indent=4))
            print(resultsDict["error"]["message"])
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
        print("No result returned")
        if addSomeDubs:
            # we've already tried it with and without www so give up.
            failedTests+=1
            toc = time.perf_counter()
            if http_response_valid:
                saveResult(site, resultsDict)
            ## todo: handle invalid http response.
        else:
            # do the test again but with www. prepended to the url
            doAxeTest(site, True)

"""
    checkSiteExists - check the http response of the site; follow redirect(s recursively)
"""
def checkSiteExists(site, ssl):
    global domain_under_test
    redirect_url = ""
    http_response_valid = 0
    htmlhead_title = ""
    htmlmeta_description = ""

    # first we'll see if it responds and check its http header
    try:
        if ssl:
            r = requests.get("https://" + site, allow_redirects=False)
        else:
            r = requests.get("http://" + site, allow_redirects=False)

        #print(r.status_code)
        # save the status_code before we do any redirecting shenanigans
        saveStatus(site, ssl, r.status_code)

        if r.status_code > 300 and r.status_code < 400:
            ## handle redirect
            redirect_url = r.headers['location']
            # if it's the same url but as https:// then we don't need to record anything new - it's the same domain/folder.
            if redirect_url != "https://" + site and redirect_url != "https://" + site + "/":
                #print("need to redirect to " + redirect_url)
                # check the new site that we've been redirected to
                if "https://" in redirect_url:
                    #print("SSL recursing " + redirect_url[8:])
                    checkSiteExists(redirect_url[8:],True)
                else:
                    #print("recursing " + redirect_url[7:])
                    checkSiteExists(redirect_url[7:], False)

        if r.status_code < 300:
            http_response_valid = True
    except requests.exceptions.RequestException as e:
        print(site + " failed to connect: ConnectionError=")
        print(e)

    if http_response_valid:
        # see if we can get some info.
        # title
        htmlheadTitleDict = re.findall('<title>(.*)</title>', r.text)
        if len(htmlheadTitleDict)>0:
            htmlhead_title = htmlheadTitleDict[0]
        # description
        htmlmetaDescriptionDict = re.findall('<meta name="description" content="(.*)"', r.text)
        if len(htmlmetaDescriptionDict)>0:
            htmlmeta_description = htmlmetaDescriptionDict[0]

        saveInfo(r.url, htmlhead_title, htmlmeta_description, domain_under_test)




"""
*******************************************
doTheLoop - cycle through all sites to test
*******************************************
"""
def doTheLoop():
    global totalTests, tic, toc
    print("Selecting data...")
    # pick a url at random
    # in the long term, the urls to test will be picked from a specific list, but for now we're testing ALL THE THINGS
    ###query = session.query(domain_register).filter(or_(domain_register.c.http_status_code=='200', domain_register.c.https_status_code=='200')).order_by(func.random())
    query = session.query(domain_register).order_by(func.random())
    rows=query.all()
    totalRows=query.count()
    for row in rows:
        print(row.domain_name)
        # check to see when we last tested this url
        oneYearAgo = datetime.datetime.now() - datetime.timedelta(days=365)
        testedRows = session.query(test_header).filter(and_(test_header.c.test_timestamp>oneYearAgo, test_header.c.domain_name==row.domain_name)).count()
        if testedRows==0:
            # we've not done this one within the last year so carry on
            tic = time.perf_counter()
            totalTests+=1
            print()
            print("****************************")
            print("Test number " , totalTests, " of ", totalRows, ": ", row.domain_name)
            print("****************************")
            checkSiteExists(row.domain_name)
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
         print ('url to test is "', singleDomain)

    if singleDomain:
       domain_under_test = singleDomain
       checkSiteExists(singleDomain, False)
       checkSiteExists(singleDomain, True)
    else:
       doTheLoop()


if __name__ == "__main__":
   main(sys.argv[1:])
