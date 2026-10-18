import type { Engine } from './contract';
export declare function createDuckDbNode(cfg: { path: string }): Promise<Engine>;
