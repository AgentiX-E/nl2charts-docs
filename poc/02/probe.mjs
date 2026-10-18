import { assembleECharts } from 'flint-chart/echarts';
const rows=[];
const regions=['East','West','North'];
for(let m=1;m<=12;m++) for(const r of regions) rows.push({month:`2026-${String(m).padStart(2,'0')}`,region:r,revenue:Math.round(1000+400*Math.sin(m/2)+(r==='East'?300:r==='West'?150:0))});
const base={data:{values:rows},semantic_types:{month:'YearMonth',region:'Country',revenue:'Amount'}};
for(const t of ['Bar Chart','Grouped Bar Chart','Stacked Bar Chart','Line Chart','Area Chart','Scatter Plot']){
  const enc = t==='Scatter Plot' ? {x:'revenue',y:'revenue'} : {x:'month',y:'revenue',color:'region'};
  try{
    const opt=assembleECharts({...base,chart_spec:{chartType:t,title:'Revenue by month',encodings:enc}});
    const series=opt.series||[];
    console.log(t,'| keys',Object.keys(opt).join(','),'| series',series.length,'| stack',JSON.stringify([...new Set(series.map(s=>s.stack))]),'| type',[...new Set(series.map(s=>s.type))].join('/'),'| w/h',opt._width,opt._height);
  }catch(e){ console.log(t,'ERR',e.message); }
}
