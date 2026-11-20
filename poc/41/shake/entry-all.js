import * as core from './src/index.js';
console.log(core.createAgent({}).ask('x'), Object.keys(core.rules).length);
