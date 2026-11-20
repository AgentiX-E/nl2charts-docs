import type { Engine } from './contract';
export declare function createDuckDbWasm(cfg: {
    opfs?: boolean;
}): Promise<Engine>;
