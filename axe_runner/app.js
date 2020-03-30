const http = require('http');
const url = require('url');
const assert = require('assert');
let axe_runner = require('./axe_runner')


const port = process.env.PORT || 3000;

const server = http.createServer((req, res) => {
  const queryObject = url.parse(req.url,true).query;
  console.log(queryObject);

  res.statusCode = 200;
  res.setHeader('Content-Type', 'text/plain');
  if(queryObject.targetURL) {
    if(!isValidURL(queryObject.targetURL)) {
        res.write('Invalid URL');
    } else {
      res.write("targetURL=" + JSON.stringify(queryObject.targetURL) + "\n");
      axeResult = axe_runner(queryObject.targetURL);
      console.log("returned");
      console.log(axeResult);
      //res.write(JSON.stringify(axeResult));
    }
  }
  res.end();
});

server.listen(port, () => {
  console.log(`Server running on ${port}/`);
});


// Cheap URL validation
const isValidURL = input => {
	const u = url.parse(input);
	return u.protocol && u.host;
};
