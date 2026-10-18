export interface Engine {
    readonly kind: string;
    query(sql: string): Promise<Record<string, unknown>[]>;
    close(): Promise<void>;
}
export declare const ENGINE_BRAND: unique symbol;
export declare const isEngine: (v: unknown) => v is Engine;
