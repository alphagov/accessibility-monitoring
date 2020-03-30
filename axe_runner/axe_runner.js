const puppeteer = require('puppeteer');
const axeCore = require('axe-core');

const runAxe2 = async url => {
  let browser;
  let results;
  try {
    // Setup Puppeteer
    console.log("setup puppeteer")
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
    console.log("Get the results from `axe.run()`");
		results = await handle.jsonValue();
		// Destroy the handle & return axe results.
		await handle.dispose();
	} catch (err) {
		// Ensure we close the puppeteer connection when possible
		if (browser) {
			await browser.close();
		}

    results = 'Error running axe-core:' + err.message;
    console.error('Error running axe-core:', err.message);
  }

  await browser.close();
  return results;
}

module.exports = function (url) {
  runAxe2(url)
	.then(results => {
    console.log("returning results...")
		//console.log("runAxe results=",results);
    return(results)
	})
	.catch(err => {
		console.error('Error running axe-core:', err.message);
		process.exit(1);
	})
}
