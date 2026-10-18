const ROWS = Array.from({ length: 200 }, (_, i) => ({ id: i + 1, region: ['east','west'][i % 2], amount: ((i * 13) % 500) / 10 }));
export function createMemoryEngine() {
  return {
    kind: 'memory',
    async query(sql) {
      const w = /where\s+region\s*=\s*'(\w+)'/i.exec(sql);
      return w ? ROWS.filter((r) => r.region === w[1]) : ROWS;
    },
  };
}
