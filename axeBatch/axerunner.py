import os, json, datetime, subprocess
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, MetaData, Table
from sqlalchemy.types import DateTime
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import or_



def axeRunner(dom2test):
    try:
        cp = subprocess.run(['axe', '--stdout', dom2test], universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return cp.stdout

    except subprocess.CalledProcessError:
        return(0)



def parseResult(jsonIn):
    # parse into python dict:
    resultsDict = json.loads(jsonIn)

    return resultsDict

def saveResult(domain_name, resultsDict):
    print(json.dumps(resultsDict[0]["url"], indent=3))

    result = session.execute(
        test_header.insert(), {"test_timestamp": resultsDict[0]["timestamp"], "url": resultsDict[0]["url"], "domain_name": domain_name, "axe_version": resultsDict[0]["testEngine"]["version"]})

    test_id = result.inserted_primary_key[0]
    print(result.inserted_primary_key)
    session.commit()

    #record data. We're doing this the long way as we want the results to say "pass" not "passes" and "violation" not "violations" etc and it's just less faff TBH
    #record violations
    count=0
    for testItem in resultsDict[0]["violations"]:
        count+=1
        result = session.execute(
            test_data.insert(), {"test_id": test_id, "rule_id": testItem["id"], "test_status": "violation", "nodes": testItem["nodes"]})
    session.commit()
    print(count, " violations recorded")

    #record passes
    count=0
    for testItem in resultsDict[0]["passes"]:
        count+=1
        result = session.execute(
            test_data.insert(), {"test_id": test_id, "rule_id": testItem["id"], "test_status": "pass", "nodes": testItem["nodes"]})
    session.commit()
    print(count, " passes recorded")

    #record inapplicable
    count=0
    for testItem in resultsDict[0]["inapplicable"]:
        count+=1
        result = session.execute(
            test_data.insert(), {"test_id": test_id, "rule_id": testItem["id"], "test_status": "inapplicable", "nodes": testItem["nodes"]})
    session.commit()
    print(count, " inapplicable tests recorded")

    #record incomplete
    count=0
    for testItem in resultsDict[0]["incomplete"]:
        count+=1
        result = session.execute(
            test_data.insert(), {"test_id": test_id, "rule_id": testItem["id"], "test_status": "incomplete", "nodes": testItem["nodes"]})
    session.commit()
    print(count, " incomplete tests recorded")


"""
    doATest - run axe on the domain, parse the results, save 'em
"""
def doATest(domain):
    axeresult = axeRunner(domain)
    if axeresult:
        resultsDict = parseResult(axeresult)
        saveResult(domain, resultsDict)

"""
******************
script entry point
******************
"""
# set to database credentials/host
# taken from local environment variable in the format postgresql+psycopg2://localuser:localuser@localhost/a11ymon
print("Connecting to ", os.getenv("DATABASE_URL"))
CONNECTION_URI = os.getenv("DATABASE_URL")

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

# need to override the reflected definition of these as it fails to recognise the auto-increment :(
test_header = Table('testresult_axe_header', metadata,
    Column('test_id',Integer, primary_key=True, autoincrement=True),
    Column('test_timestamp',DateTime(timezone=True), default=func.now()),
    Column('url', String),
    Column('domain_name',String),
    Column('axe_version',String),
    schema='a11ymon',
    extend_existing=True
)
test_data = Table('testresult_axe_data', metadata,
    Column('test_data_id',Integer, primary_key=True, autoincrement=True),
    Column('test_id', Integer),
    Column('rule_id', String),
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
    schema='pubsecdomains',
    extend_existing=True
)

# pick a domain at random
# (later enhancement - look it up in test table to see if we've done it this year if not, test it.)
totalTests = 0
rows = session.query(domain_register).order_by(func.random()).all()
for row in rows:
    if (row.http_status_code=="200") | (row.https_status_code=="200"):
        totalTests+=1
        print("****************************")
        print("Test number " , totalTests, ": ", row.domain_name)
        print("****************************")
        doATest(row.domain_name)

print(".")
print("****************************")
print("Total tests: " , totalTests)
print("****************************")
