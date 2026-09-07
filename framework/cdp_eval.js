// CDP evaluate helper — runs a JS expression and prints the result
// Usage: node cdp_eval.js ws://127.0.0.1:PORT/devtools/page/ID eval "<expression>"
//        node cdp_eval.js ws://127.0.0.1:PORT/devtools/page/ID nav "<url>"
const WebSocket = require('ws');
const WS_URL = process.argv[2];
const MODE = process.argv[3];     // 'eval' or 'nav'
const PAYLOAD = process.argv[4];

let ws;
let msgId = 1;
const pending = new Map();

function cdp(method, params) {
  return new Promise((resolve, reject) => {
    const id = msgId++;
    ws.send(JSON.stringify({id, method, params}));
    const timeout = setTimeout(() => reject(new Error('Timeout: ' + method)), 30000);
    pending.set(id, {resolve, reject, timeout});
  });
}

ws = new WebSocket(WS_URL);
ws.on('open', async () => {
  try {
    if (MODE === 'nav') {
      await cdp('Page.navigate', {url: PAYLOAD});
      console.log(JSON.stringify({status: 'navigated', url: PAYLOAD}));
    } else if (MODE === 'eval') {
      const r = await cdp('Runtime.evaluate', {
        expression: PAYLOAD,
        returnByValue: true,
        awaitPromise: true
      });
      const result = r.result && r.result.result ? r.result.result.value : null;
      console.log(JSON.stringify({status: 'ok', result}));
    } else {
      throw new Error('Unknown mode: ' + MODE);
    }
    ws.close();
    process.exit(0);
  } catch (e) {
    console.error(JSON.stringify({status: 'error', message: e.message}));
    ws.close();
    process.exit(1);
  }
});
ws.on('message', (data) => {
  const msg = JSON.parse(data.toString());
  if (msg.id && pending.has(msg.id)) {
    const {resolve, timeout} = pending.get(msg.id);
    clearTimeout(timeout);
    pending.delete(msg.id);
    resolve(msg);
  }
});
ws.on('error', (e) => {
  console.error(JSON.stringify({status: 'ws_error', message: e.message}));
  process.exit(1);
});
