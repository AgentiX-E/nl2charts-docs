export const connectorSchema = { type:'object', required:['host','port','database','user','password'], properties:{
 host:{type:'string',title:'主机',description:'例如 db.internal'},
 port:{type:'integer',title:'端口'}, database:{type:'string',title:'数据库'},
 user:{type:'string',title:'用户名'}, password:{type:'string',format:'password',title:'密码'},
 ssl:{type:'boolean',title:'使用 TLS'}, schema:{type:'string',title:'默认 Schema'},
 catalog:{type:'string',title:'Catalog'}, readOnly:{type:'boolean',title:'只读'},
 maxConns:{type:'integer',title:'最大连接数'}, timeoutSec:{type:'integer',title:'超时(秒)'},
 sslMode:{type:'string',title:'SSL 模式',enum:['disable','require','verify-full']} } };
