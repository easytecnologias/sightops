const fs = require('fs');
const vm = require('vm');

const deployJs = fs.readFileSync('frontend/js/deploy.js', 'utf8');
const connectorsJs = fs.readFileSync('frontend/js/connectors.js', 'utf8');

const context = {
  console,
  window: {},
  document: {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    body: { appendChild: () => {}, classList: { add: () => {}, remove: () => {} } },
  },
  lucide: { createIcons: () => {} },
};

vm.createContext(context);
vm.runInContext(deployJs, context, { filename: 'frontend/js/deploy.js' });
vm.runInContext(connectorsJs, context, { filename: 'frontend/js/connectors.js' });

const row = {
  inventory: {
    address_sample: [
      '100.65.10.1/22|BRIDGE DAS CAMERAS',
      '179.97.32.50/30|ether10',
      '192.168.50.1/30|VLAN_800_GERENCIA',
      '10.250.0.6/24|sightops-wg',
    ].join(';'),
  },
};

const lans = context.connectorDetectedLans(row);
if (!lans.includes('100.65.8.0/22')) {
  throw new Error(`CGNAT da rede de cameras nao apareceu: ${JSON.stringify(lans)}`);
}
if (!lans.includes('192.168.50.0/30')) {
  throw new Error(`Rede de gerencia nao apareceu: ${JSON.stringify(lans)}`);
}
if (lans.some(item => item.startsWith('179.97.'))) {
  throw new Error(`Link publico entrou indevidamente: ${JSON.stringify(lans)}`);
}
if (lans.includes('10.250.0.0/24')) {
  throw new Error(`Rede WireGuard entrou indevidamente: ${JSON.stringify(lans)}`);
}

console.log('OK frontend connector CGNAT LAN detection', lans);
