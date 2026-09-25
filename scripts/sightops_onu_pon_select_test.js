const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('frontend/js/deploy.js', 'utf8');
const sandbox = {
  console,
  document: { getElementById: () => null, querySelectorAll: () => [] },
  window: {},
  lucide: { createIcons: () => {} },
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

function check(cond, msg, failures) {
  if (!cond) failures.push(msg);
}

function makeSelect(value = '') {
  return {
    value,
    options: [],
    innerHTML: '',
    set innerHTML(html) {
      this._html = html;
      const matches = [...html.matchAll(/<option value="([^"]*)">([^<]*)<\/option>/g)];
      this.options = matches.map(match => ({ value: match[1], text: match[2] }));
    },
    get innerHTML() {
      return this._html || '';
    },
  };
}

const failures = [];

check(sandbox.onuPonCountForRow({ driver: 'intelbras_4840e', model: '4840E' }) === 4, '4840E deve ter 4 PONs', failures);
check(sandbox.onuPonCountForRow({ driver: 'intelbras_8820i', model: '8820i' }) === 8, '8820i deve manter 8 PONs', failures);
check(sandbox.onuPonCountForRow({ model: 'AN5516-06' }) === 8, 'modelo desconhecido/FiberHome deve manter padrao 8 PONs', failures);

const allSelect = makeSelect('all');
sandbox.onuRenderPonSelectOptions(allSelect, 4, true);
check(allSelect.options.length === 5, `select Todas 4840E deveria ter 5 opcoes, veio ${allSelect.options.length}`, failures);
check(allSelect.options[0].text === 'Todas (1-4)', `label Todas errado: ${allSelect.options[0].text}`, failures);
check(allSelect.options.at(-1).text === 'PON 4', `ultima PON 4840E errada: ${allSelect.options.at(-1).text}`, failures);

const querySelect = makeSelect('7');
sandbox.onuRenderPonSelectOptions(querySelect, 4, false);
check(querySelect.value === '', `valor invalido deveria limpar, veio ${querySelect.value}`, failures);
check(!querySelect.options.some(opt => opt.value === '5'), '4840E nao deve renderizar PON 5', failures);

if (failures.length) {
  console.error(`FALHOU (${failures.length}):`);
  for (const failure of failures) console.error(' -', failure);
  process.exit(1);
}

console.log('OK ONU PON selector is model-aware');
