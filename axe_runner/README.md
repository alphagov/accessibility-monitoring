# Axe-Runner

Runs the [Deque Axe Core API](https://github.com/dequelabs/axe-core) against a headless Google Chrome browser and returns the results in JSON.

It has been designed to run in [GOV.UK's Platform-as-a-Service (PaaS)](https://www.cloud.service.gov.uk/), which is based upon [CloudFoundry](https://www.cloudfoundry.org/).

This is a _prototype_ service. **It is NOT production-ready.**

## Usage
[script_location]]/?targetURL=https://www.test.site

### Output
Returns the JSON output of Axe directly, or a JSON-encapsulated error message:  
```
{
  "error" : {
    "type" : "system" | "user",
    "message" : "Really useful description of the problem"
  }
}
```

## Notes on design
The "traditional" way to use Axe is to use [Axe Webdriver.js](https://github.com/dequelabs/axe-webdriverjs) in conjunction with [Selenium](https://www.selenium.dev/) and your choice of webdriver/browser (Chrome, Firefox etc) and have Axe inject its code into the page, run, and report results back via a callback.

This works fine if you're running it on a PC/terminal with an actual browser, but we don't have that. What we have is a human-free process somewhere in the cloud. And because this is going in a container, we have to supply absolutely everything that is needed and make sure that each part (axe, selenium, (headless-)browser) can see the other.

And that's where the problem lies:  
Axe controls Selenium.   
Selenium controls the browser (headless chrome in this case).  
But Selenium needs to know the path to the browser, and when you install Chrome via [apt](https://www.debian.org/doc/manuals/debian-reference/ch02.en.html) (the only way that I can find to do it in [CloudFoundry](https://www.cloudfoundry.org/), it puts it somewhere that isn't in the path and isn't in the usual places that Selenium would expect it.  
There is no way to get Axe to tell Selenium where the Chrome browser is. (There's a `path` option but that's for Chromedriver, not Chrome).

The solution was to (temporarily, I hope) abandon the dream of multiple browser support via Selenium, and use Google's [Puppeteer](https://developers.google.com/web/tools/puppeteer) library to control [Chromium](https://www.chromium.org/Home).   
Puppeteer is bundled with Chromium, so it's guaranteed to know where to find it.
