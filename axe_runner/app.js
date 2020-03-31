const http = require('http');
const url = require('url');
const assert = require('assert');

const puppeteer = require('puppeteer');
const axeCore = require('axe-core');



const port = process.env.PORT || 3000;

const server = http.createServer((req, res) => {
  const queryObject = url.parse(req.url,true).query;

  res.statusCode = 200;
  res.setHeader('Content-Type', 'text/plain');
  if(queryObject.targetURL) {
    if(!isValidURL(queryObject.targetURL)) {
        res.write('Invalid URL');
    } else {
      // run axe...
      runAxe2(queryObject.targetURL)
      	.then(results => {
          console.log("runAxe2 returned OK");
          res.end(JSON.stringify(results));
      	})
      	.catch(err => {
      		console.error('Error running axe-core (in main):', err.message);
          res.end("Bloop");
      		process.exit(1);
      	})

      console.log("returned");
    }
  }
});

server.listen(port, () => {
  console.log(`Server running on ${port}/`);
});


// Cheap URL validation
const isValidURL = input => {
	const u = url.parse(input);
	return u.protocol && u.host;
};

const runAxe2 = async url => {
  let browser;
  let results;
  try {
    // Setup Puppeteer
    browser = await puppeteer.launch({args: ['--no-sandbox', '--disable-setuid-sandbox']});

    // Get new page
		const page = await browser.newPage();
    // console.info(browser);
    console.log("going to ", url)
		await page.goto(url);

		// Inject and run axe-core
		const handle = await page.evaluateHandle(`
			// Inject axe source code
			${axeCore.source}
			// Run axe
			axe.run()
		`);

		// Get the results from `axe.run()`.
		results = await handle.jsonValue();
		// Destroy the handle & return axe results.
		await handle.dispose();
	} catch (err) {
		// Ensure we close the puppeteer connection when possible
		if (browser) {
			await browser.close();
		}

    results = 'Error running axe-core (in runAxe2):' + err.message;
    console.error('Error running axe-core (in runAxe2):', err.message);
  }

  await browser.close();
  return results;
}
