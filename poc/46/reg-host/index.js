import * as A from '../reg-a/index.js';
import * as B from '../reg-b/index.js';

// node package registers through copy B, host resolves through copy A
B.register('pg', () => 'pg-engine');
B.NAIVE.set('pg', () => 'pg-engine');

const rows = [
  { reg: 'naive Map  (A sees B?)', value: A.NAIVE.get('pg') !== undefined, expected: false },
  { reg: 'globalThis (A sees B?)', value: A.resolve('pg') !== undefined, expected: true },
];
console.log(JSON.stringify(rows, null, 1));
console.log(rows.every(r => r.value === r.expected) ? 'REGISTRY: naive BROKEN, shared OK' : 'UNEXPECTED');
