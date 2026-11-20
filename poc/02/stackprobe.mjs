import { assembleECharts } from 'flint-chart/echarts';
const rows=[];for(let m=1;m<=12;m++)for(const r of ['East','West','North'])rows.push({month:`2026-${String(m).padStart(2,'0')}`,region:r,revenue:1000+m*10});
const base={data:{values:rows},semantic_types:{month:'YearMonth',region:'Country',revenue:'Amount'}};
const enc={x:'month',y:'revenue',color:'region'};
const cases=[
 ['Grouped Bar / no flag',{chartType:'Grouped Bar Chart',encodings:enc}],
 ['Grouped Bar / stack:true',{chartType:'Grouped Bar Chart',encodings:enc,stack:true}],
 ['Grouped Bar / stack:false',{chartType:'Grouped Bar Chart',encodings:enc,stack:false}],
 ['Bar Chart / stack:false',{chartType:'Bar Chart',encodings:enc,stack:false}],
 ['Bar Chart / no flag',{chartType:'Bar Chart',encodings:enc}],
 ['Area Chart / stack:false',{chartType:'Area Chart',encodings:enc,stack:false}],
];
for(const [name,spec] of cases){
  try{
    const o=assembleECharts({...base,chart_spec:spec});
    console.log(name,'-> stack=',JSON.stringify([...new Set(o.series.map(s=>s.stack??null))]));
  }catch(e){console.log(name,'ERR',e.message.slice(0,60));}
}
