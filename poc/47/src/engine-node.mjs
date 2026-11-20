// Node-only engine. The node:fs import is deliberate: it makes this module
// unresolvable for a browser bundler, which is the physical proof of "node-only".
import { statSync } from 'node:fs';

const ROWS = Array.from({ length: 1000 }, (_, i) => ({
  id: i + 1,
  region: ['east', 'west', 'north'][i % 3],
  amount: ((i * 37) % 1000) / 10,
}));

export function createNodeEngine(cfg = {}) {
  return {
    kind: 'node-engine',
    // proves the module really touched the filesystem API at load time
    probed: typeof statSync === 'function',
    async query(sql) {
      const where = /where\s+region\s*=\s*'(\w+)'/i.exec(sql);
      const rows = where ? ROWS.filter((r) => r.region === where[1]) : ROWS;
      const limit = /limit\s+(\d+)/i.exec(sql);
      return limit ? rows.slice(0, Number(limit[1])) : rows;
    },
    async close() {},
  };
}
