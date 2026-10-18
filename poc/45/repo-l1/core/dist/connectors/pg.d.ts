export declare function createPgConnector(cfg: {
    host: string;
}): {
    kind: string;
    connect: () => import("net").Socket;
};
