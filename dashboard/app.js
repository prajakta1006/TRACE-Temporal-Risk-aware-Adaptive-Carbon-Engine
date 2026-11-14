const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const fmt = (value, digits = 0) => Number(value ?? 0).toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits });
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {fifo:'FIFO', earliest_feasible:'Earliest-feasible', trace:'Forecast-guided TRACE'};
let data = null;

async function loadData() {
  $('#refresh').classList.add('spinning');
  try {
    const response = await fetch('/api/dashboard', {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    data = await response.json();
    if (!data.available || !data.result) throw new Error('Phase 6 result not found');
    $('#load-error').hidden = true;
    $('#loading-state').hidden = true;
    renderDashboard();
  } catch (error) {
    console.error('Could not load TRACE experiment artifacts', error);
    $('#load-error').hidden = false;
    $('#loading-state').hidden = true;
    renderEmptyCharts();
  } finally { $('#refresh').classList.remove('spinning'); }
}

function strategyEntries() { return Object.entries(data.result.strategy_results || {}); }
function traceMetrics() { return data.result.strategy_results.trace || {}; }
function commonMetrics() { return data.result.common_population || {}; }
function percent(value) { return `${Number(value || 0).toFixed(2)}%`; }
function animateValue(selector, value, formatter = fmt) {
  const node=$(selector); if(!node)return;
  const target=Number(value||0), start=performance.now(), duration=680;
  if(!Number.isFinite(target)){node.textContent='Unavailable';return;}
  function frame(now){const p=Math.min(1,(now-start)/duration), eased=1-Math.pow(1-p,3);node.textContent=formatter(target*eased);if(p<1)requestAnimationFrame(frame);}
  requestAnimationFrame(frame);
}

function renderDashboard() {
  const run = data.result, trace = traceMetrics(), config = data.config?.simulation || {};
  const common = commonMetrics(), commonEmissions = common.common_population_observed_emissions_g_co2e || {};
  const savedPct = run.common_population_emissions_comparison_vs_fifo?.trace?.percent_difference_vs_fifo ?? 0;
  animateValue('#kpi-processed',run.tasks_processed);
  animateValue('#kpi-energy',trace.completed_energy_kwh,v=>fmt(v,2));
  animateValue('#kpi-emissions',trace.completed_observed_emissions_g_co2e,v=>fmt(v,1));
  animateValue('#kpi-completion',trace.completion_rate*100,v=>fmt(v,2));
  animateValue('#kpi-done',trace.completed_tasks);
  animateValue('#kpi-deferred',trace.deferred_tasks);
  animateValue('#kpi-forecast-eligible',trace.forecast_eligible_tasks);
  animateValue('#kpi-utilization',trace.average_capacity_utilization_fraction*100,v=>fmt(v,1));
  $('#kpi-completed-caption').textContent = `${fmt(trace.completed_tasks)} completed`;
  $('#hero-savings').textContent = `${Math.abs(savedPct).toFixed(3)}%`;
  $('#common-savings').innerHTML = `${Math.abs(savedPct).toFixed(3)}<small>%</small>`;
  $('#common-count').textContent = fmt(common.common_executed_tasks);
  $('#execution-total').textContent = fmt(run.tasks_processed);
  $('#exec-done').textContent = fmt(trace.completed_tasks);
  $('#exec-deferred').textContent = fmt(trace.deferred_tasks);
  $('#exec-infeasible').textContent = fmt(trace.infeasible_tasks);
  $('#completion-progress').style.width = `${Math.min(100, trace.completion_rate * 100)}%`;
  $('#cpu-capacity').textContent = `${fmt(config.cpu_capacity)} cores`;
  $('#constraint-violations').textContent = fmt((trace.capacity_violations || 0) + (trace.task_constraint_violations || 0));
  renderComparisonBars(commonEmissions);
  renderStrategyChart();
  renderForecastChart();
  renderResearchStrip();
  $('#overview-results').innerHTML=strategyEntries().map(([key,m])=>`<tr><td><b>${esc(labels[key])}</b></td><td>${fmt(m.completed_tasks)}</td><td>${fmt(m.deferred_tasks)}</td><td>${fmt(m.scheduled_energy_kwh,3)} kWh</td><td>${fmt(m.completed_observed_emissions_g_co2e,1)} g</td><td>${percent(m.average_capacity_utilization_fraction*100)}</td></tr>`).join('');
  renderPages();
  const created = data.config?.created_utc;
  $('#footer-updated').textContent = created ? `RUN COMPLETED ${new Date(created).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric'}).toUpperCase()}` : 'LOCAL EXPERIMENT ARTIFACTS';
}

function renderResearchStrip(){
  const all=(data.forecast_accuracy||[]).find(r=>r.horizon_hours==='all'&&r.model==='rolling_seasonal_naive_24h')||{};
  const carbon=data.carbon_summary||{}, passed=Object.values(data.independent?.strategies||{}).filter(s=>s.passed).length;
  $('#tile-forecast-mae').textContent=all.mae?fmt(all.mae,3):'Unavailable';
  $('#tile-audit').textContent=data.independent?.completed?`${passed} / 3 PASS`:'Unavailable';
  $('#tile-audit-caption').textContent=data.cross_check?.completed?'ledger IDs, checkpoints & energy reconciled':'independent reconciliation artifact unavailable';
  $('#tile-carbon-range').textContent=carbon.min!=null?`${fmt(carbon.min)}–${fmt(carbon.max)}`:'Unavailable';
  $('#tile-fallbacks').textContent=fmt(traceMetrics().forecast_fallback_decisions);
}

function renderComparisonBars(values) {
  const base = Number(values.fifo || 1);
  $('#common-bars').innerHTML = Object.entries(values).map(([key,value]) => `<div class="mini-bar-row"><span>${esc(labels[key] || key)}</span><div class="mini-track"><i style="width:${Math.min(100,Number(value)/base*100)}%"></i></div><b>${fmt(value,2)} g</b></div>`).join('');
}

function svgLineChart(series, {height=190, labelsX=true, yLabel='', bands=[]}={}) {
  const width=760, left=47, right=15, top=12, bottom=labelsX?27:12, plotW=width-left-right, plotH=height-top-bottom;
  const points=[...series.flatMap(s=>s.values.map(p=>p.y)),...bands.flatMap(b=>[...b.low,...b.high].map(p=>Number(p.y??p)))].filter(Number.isFinite);
  if (!points.length) return '<div class="empty-state">No data available in these artifacts.</div>';
  const min=Math.min(...points), max=Math.max(...points), pad=(max-min||1)*.13, lo=min-pad, hi=max+pad;
  const times=series.flatMap(s=>s.values.map(p=>p.x).filter(Number.isFinite)), timeScale=times.length>1, timeMin=Math.min(...times), timeMax=Math.max(...times);
  const x=(i,n,p)=>left+(timeScale?((Number.isFinite(p?.x)?p.x:timeMin)-timeMin)/(timeMax-timeMin||1):(n<2?0:i/(n-1)))*plotW, y=v=>top+(hi-v)/(hi-lo)*plotH;
  const grid=[0,1,2,3].map(i=>{const yy=top+i*plotH/3, val=hi-i*(hi-lo)/3;return `<line x1="${left}" y1="${yy}" x2="${width-right}" y2="${yy}" stroke="#edf0eb"/><text x="${left-7}" y="${yy+3}" text-anchor="end" fill="#a0a69e" font-size="9">${fmt(val,0)}</text>`}).join('');
  const bandMarkup=bands.map(b=>{const n=Math.min(b.low.length,b.high.length);if(!n)return '';const upper=b.high.map((p,i)=>`${x(i,n,p)},${y(Number(p.y??p))}`).join(' '), lower=b.low.map((p,i)=>`${x(n-1-i,n,b.low[n-1-i])},${y(Number(b.low[n-1-i].y??b.low[n-1-i]))}`).join(' ');return `<polygon points="${upper} ${lower}" fill="#dfe9d6" opacity=".58"/>`}).join('');
  const lines=series.map(s=>{const n=s.values.length; if(!n)return ''; const coords=s.values.map((p,i)=>`${x(i,n,p)},${y(p.y)}`).join(' ');return `<polyline points="${coords}" fill="none" stroke="${s.color}" stroke-width="2.2" ${s.dash?'stroke-dasharray="5 4"':''} stroke-linecap="round" stroke-linejoin="round"/>`}).join('');
  const dots=series.map(s=>s.values.map((p,i)=>`<circle cx="${x(i,s.values.length,p)}" cy="${y(p.y)}" r="2.6" fill="${s.color}"><title>${esc(p.label||'')} · ${fmt(p.y,1)}</title></circle>`).join('')).join('');
  const n=Math.max(...series.map(s=>s.values.length));
  const tickValues=timeScale?Array.from({length:6},(_,i)=>timeMin+(timeMax-timeMin)*i/5):null;
  const xlabels=labelsX&&(timeScale?tickValues.map(t=>{const dt=new Date(t);return `<text x="${x(0,1,{x:t})}" y="${height-5}" text-anchor="middle" fill="#a0a69e" font-size="8">${dt.toLocaleDateString('en-GB',{day:'numeric',month:'short'})}</text>`}).join(''):series[0].values.map((p,i)=>i%Math.max(1,Math.ceil(n/6))===0||i===n-1?`<text x="${x(i,n,p)}" y="${height-5}" text-anchor="middle" fill="#a0a69e" font-size="8">${esc(p.label||'')}</text>`:'').join(''));
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(yLabel)} time series chart">${grid}${bandMarkup}${lines}${dots}${xlabels}</svg>`;
}

function metricValue(m, metric) {
  if (metric==='energy') return Number(m.completed_energy_kwh || m.scheduled_energy_kwh || 0);
  if (metric==='completed') return Number(m.completed_tasks || 0);
  if (metric==='deferred') return Number(m.deferred_tasks || 0);
  if (metric==='infeasible') return Number(m.infeasible_tasks || 0);
  if (metric==='completion') return Number(m.completion_rate || 0)*100;
  if (metric==='utilization') return Number(m.average_capacity_utilization_fraction || 0)*100;
  return Number(m.completed_observed_emissions_g_co2e || m.scheduled_observed_emissions_g_co2e || 0);
}
function renderStrategyChart() {
  const metric=$('#comparison-metric').value, colors={fifo:'#96a39a',earliest_feasible:'#d2b27f',trace:'#789d64'};
  const rows=strategyEntries(), max=Math.max(1,...rows.map(([,m])=>metricValue(m,metric)));
  const width=760,height=205,left=72,right=70,top=16,bottom=22,plotW=width-left-right,plotH=height-top-bottom;
  const bars=rows.map(([key,m],i)=>{const val=metricValue(m,metric), y=top+i*(plotH/3)+7, w=val/max*plotW;let shown=metric==='utilization'||metric==='completion'?`${fmt(val,2)}%`:metric==='completed'||metric==='deferred'||metric==='infeasible'?fmt(val):metric==='energy'?`${fmt(val,3)} kWh`:`${fmt(val,1)} g`;return `<text x="${left-10}" y="${y+12}" text-anchor="end" fill="#727b72" font-size="10">${esc(labels[key])}</text><rect x="${left}" y="${y}" width="${plotW}" height="19" rx="5" fill="#f3f5f1"/><rect x="${left}" y="${y}" width="${Math.max(2,w)}" height="19" rx="5" fill="${colors[key]}"><title>${esc(labels[key])}: ${shown}</title></rect><text x="${Math.min(width-right+5,left+w+8)}" y="${y+13}" fill="#697169" font-size="9">${shown}</text>`}).join('');
  const caption={emissions:'Observed emissions · g CO₂e',energy:'Modelled scheduled energy · kWh',completed:'Completed tasks',deferred:'Deferred tasks',infeasible:'Infeasible tasks',completion:'Completion rate · %',utilization:'Average CPU utilization · %'}[metric];
  $('#strategy-chart').innerHTML=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${caption}">${[0,.25,.5,.75,1].map(v=>`<line x1="${left+plotW*v}" y1="${top}" x2="${left+plotW*v}" y2="${height-bottom}" stroke="#edf0eb"/>`).join('')}${bars}</svg>`;
}

function renderForecastChart() {
  const carbon=(data.carbon||[]).filter(r=>r.datetime&&Number.isFinite(Number(r.carbonIntensity)));
  const forecasts=(data.forecasts||[]).filter(r=>r.timestamp_utc&&Number.isFinite(Number(r.predicted_carbon_intensity)));
  if(!carbon.length){$('#forecast-chart').innerHTML='<div class="empty-state">Observed carbon series is unavailable.</div>';return;}
  const sample=carbon.length>90?carbon.filter((_,i)=>i%Math.ceil(carbon.length/70)===0):carbon;
  const actual=sample.map(r=>({x:Date.parse(r.datetime),y:Number(r.carbonIntensity),label:new Date(r.datetime).toLocaleString()}));
  const latestOrigin=forecasts.map(r=>r.forecast_origin_utc).sort().at(-1);
  const replay=forecasts.filter(r=>r.forecast_origin_utc===latestOrigin).sort((a,b)=>Number(a.horizon_hours)-Number(b.horizon_hours)).map(r=>({x:Date.parse(r.timestamp_utc),y:Number(r.predicted_carbon_intensity),label:`${r.horizon_hours}h forecast · ${r.timestamp_utc}`}));
  const lower=replay.map((p,i)=>({x:p.x,y:Number(forecasts.filter(r=>r.forecast_origin_utc===latestOrigin).sort((a,b)=>Number(a.horizon_hours)-Number(b.horizon_hours))[i].lower_bound)}));
  const upper=replay.map((p,i)=>({x:p.x,y:Number(forecasts.filter(r=>r.forecast_origin_utc===latestOrigin).sort((a,b)=>Number(a.horizon_hours)-Number(b.horizon_hours))[i].upper_bound)}));
  $('#forecast-chart').innerHTML=svgLineChart([{values:actual,color:'#75946a'},{values:replay,color:'#d1a35d',dash:true}],{height:185,labelsX:true,yLabel:'Carbon intensity',bands:[{low:lower,high:upper}]});
}

function header(eyebrow,title,description){return `<div class="detail-head"><div><div class="eyebrow muted">${eyebrow}</div><h1>${title}</h1><p>${description}</p></div></div>`}
function metricCards(items){return `<div class="detail-cards">${items.map(([label,value,caption])=>`<article class="detail-card"><label>${label}</label><strong>${value}</strong><small>${caption}</small></article>`).join('')}</div>`}
function table(headers,rows){return `<div style="overflow-x:auto"><table class="data-table"><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map((v,i)=>`<td>${i===0?`<b>${v}</b>`:v}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function resultRows(){return strategyEntries().map(([k,m])=>[esc(labels[k]),fmt(m.completed_tasks),fmt(m.deferred_tasks),fmt(m.infeasible_tasks),`${fmt(m.scheduled_energy_kwh,3)} kWh`,`${fmt(m.completed_observed_emissions_g_co2e,3)} g`,`${fmt(m.common_population_observed_emissions_g_co2e,3)} g`,percent(m.average_capacity_utilization_fraction*100)]);}
function renderPages(){
  const run=data.result, trace=traceMetrics(), cfg=data.config||{}, sim=cfg.simulation||{}, strategies=strategyEntries(), common=commonMetrics();
  const set=(key,html)=>{const el=$(`#view-${key}`);if(el)el.innerHTML=html};
  set('simulation',header('PHASE 6 · COMPLETED RUN','Simulation overview','Full chronological workload replay with fixed CPU capacity and bounded task delay.')+
    metricCards([['Tasks processed',fmt(run.tasks_processed),'Complete validated chronological input'],['Strategies evaluated','03','FIFO · Earliest-feasible · TRACE'],['Run duration',`${fmt(run.runtime_seconds/3600,2)} h`,'Recorded simulation runtime'],['Experiment zone',esc(cfg.zone||'IN-WE'),'Carbon intensity region']])+`<div class="detail-grid"><article class="detail-panel"><h3>Simulation configuration</h3>${table(['SETTING','VALUE'],[['CPU capacity',`${fmt(sim.cpu_capacity)} cores`],['Maximum delay',`${fmt(sim.max_delay_seconds)} seconds`],['Forecast horizon',`${fmt(sim.forecast_horizon)} hours`],['Risk weight',fmt(sim.risk_weight,2)],['Power model',`${fmt(sim.power_per_core_watts)} W / core`],['Sampling','Complete workload; no task limit']])}</article><article class="detail-panel"><h3>Run status</h3><p><span class="pill">Completed</span> &nbsp; All three strategy ledgers completed and were independently reconciled.</p><p>${fmt(trace.capacity_violations)} capacity violations and ${fmt(trace.task_constraint_violations)} task constraint violations in TRACE.</p><p>Simulation duration: ${fmt(run.runtime_seconds,1)} seconds. Peak process RSS: ${fmt(run.peak_rss_bytes/1024/1024,1)} MB.</p></article></div>`);
  set('strategies',header('SCHEDULING POLICIES','Scheduling strategies','Compare the policy rules and their measured outcomes from the full Phase 6 run.')+`<article class="detail-panel"><h3>How the policies decide</h3><div class="detail-grid"><p><b>FIFO</b><br>Preserves chronological task order and finds feasible slots without overtaking committed starts.</p><p><b>Earliest-feasible</b><br>Chooses the earliest capacity-feasible slot and can backfill available gaps.</p><p><b>Forecast-guided TRACE</b><br>Ranks feasible hourly starts using predicted carbon savings reduced by forecast uncertainty, with earliest-feasible fallback.</p><p><b>Shared constraints</b><br>Non-preemptive scheduling; 8-core capacity; release-time and 3,600-second maximum-delay constraints for this experiment.</p></div></article><article class="detail-panel"><h3>Observed experiment results</h3>${table(['STRATEGY','COMPLETED','DEFERRED','INFEASIBLE','ENERGY','EMISSIONS','CPU USE'],strategies.map(([k,m])=>[esc(labels[k]),fmt(m.completed_tasks),fmt(m.deferred_tasks),fmt(m.infeasible_tasks),`${fmt(m.scheduled_energy_kwh,3)} kWh`,`${fmt(m.completed_observed_emissions_g_co2e,2)} g`,percent(m.average_capacity_utilization_fraction*100)]))}</article>`);
  const forecastRows=(data.forecasts||[]).slice(0,40).map(r=>[esc((r.forecast_origin_utc||'').slice(0,16).replace('T',' ')),esc((r.timestamp_utc||'').slice(0,16).replace('T',' ')),`${esc(r.horizon_hours)} h`,`${fmt(r.predicted_carbon_intensity,1)} g/kWh`,`${fmt(r.actual_carbon_intensity,1)} g/kWh`,r.covered==='True'?'<span class="pill">Covered</span>':'—']);
  const accuracy=(data.forecast_accuracy||[]).filter(r=>r.model==='rolling_seasonal_naive_24h');
  const allAccuracy=accuracy.find(r=>r.horizon_hours==='all')||{};
  const coverage=data.forecast_coverage?.[0]||{};
  const forecastCards=[['Evaluation rows',fmt(data.forecast_summary?.evaluation_rows),'Rolling-origin historical replay'],['All-lead MAE',allAccuracy.mae?`${fmt(allAccuracy.mae,3)} g/kWh`:'Unavailable','160 replayed predictions'],['All-lead RMSE',allAccuracy.rmse?`${fmt(allAccuracy.rmse,3)} g/kWh`:'Unavailable','Observed held-out carbon'],['Interval coverage',allAccuracy.prediction_interval_coverage?percent(Number(allAccuracy.prediction_interval_coverage)*100):'Unavailable','short correlated sample; not calibrated']];
  set('forecasting',header('HISTORICAL REPLAY · NOT LIVE','Carbon forecasting','Seasonal Naive forecast replay evaluated against held-out IN-WE observations.')+metricCards(forecastCards)+`<article class="detail-panel"><h3>Observed grid signal & replay forecast</h3><p>Carbon observations span 22–30 September 2026. Replay: ${fmt(coverage.forecast_origins)} origins · ${esc(coverage.forecast_horizons||'1–4')} hourly leads · ${fmt(coverage.forecast_records)} records.</p><div id="forecast-detail-chart" class="chart-area" style="height:260px"></div><p>Latest-origin forecast horizon is shown beyond the observed series where available. Intervals are replay uncertainty bands, not a live confidence statement.</p></article><article class="detail-panel"><h3>Error and interval coverage by horizon</h3>${table(['HORIZON','PREDICTIONS','MAE · g/kWh','RMSE · g/kWh','BIAS · g/kWh','INTERVAL COVERAGE','AVG WIDTH · g/kWh'],accuracy.map(r=>[esc(r.horizon_hours==='all'?'All leads':`${r.horizon_hours} h`),fmt(r.prediction_count),fmt(r.mae,3),fmt(r.rmse,3),fmt(r.mean_error_bias,3),r.prediction_interval_coverage?percent(Number(r.prediction_interval_coverage)*100):'—',r.average_interval_width?fmt(r.average_interval_width,1):'—']))}</article><article class="detail-panel"><h3>Forecast replay records</h3><p>Showing up to 40 persisted records. Predictions are historical replay, not current grid forecasts.</p>${table(['ORIGIN (UTC)','TARGET (UTC)','HORIZON','PREDICTED','OBSERVED','COVERAGE'],forecastRows)}</article>`);
  const perTask=trace.completed_tasks?trace.completed_energy_kwh/trace.completed_tasks:0;
  set('energy',header('ENERGY · CARBON','Energy analytics','Modelled task energy and observed emissions from the completed strategy ledgers.')+metricCards([['Power assumption',`${fmt(sim.power_per_core_watts)} W / core`,'Assumed constant; not measured'],['TRACE modelled energy',`${fmt(trace.completed_energy_kwh,3)} kWh`,'duration × cores × power'],['Energy per completed task',`${fmt(perTask*1000,3)} Wh`,'Derived from TRACE ledger totals'],['TRACE observed emissions',`${fmt(trace.completed_observed_emissions_g_co2e,2)} g CO₂e`,'Observed IN-WE carbon intensity']])+`<article class="detail-panel"><h3>Strategy energy and emissions</h3>${table(['STRATEGY','TASKS COMPLETED','MODELLED ENERGY','OBSERVED EMISSIONS','COMMON TASK EMISSIONS'],resultRows())}<p>Energy follows duration × allocated cores × 10 W/core. Emissions are calculated using observed carbon intensity over scheduled intervals. These are model outputs, not metered data-center measurements.</p></article>`);
  const statuses=[['Completed',trace.completed_tasks,'Executed and covered by carbon series'],['Deferred',trace.deferred_tasks,'No capacity slot within maximum delay'],['Infeasible',trace.infeasible_tasks,'CPU request exceeds configured capacity']];
  set('execution',header('TASK LEDGER · TRACE','Task execution','Aggregate task outcomes from the TRACE strategy ledger.')+metricCards(statuses.map(([a,b,c])=>[a,fmt(b),c]))+`<article class="detail-panel"><h3>Execution constraints and forecast use</h3>${table(['MEASURE','VALUE','INTERPRETATION'],[['CPU capacity',`${fmt(sim.cpu_capacity)} cores`,'Maximum concurrent allocation'],['Peak allocated CPU',trace.independent_peak_allocated_cores!=null?`${fmt(trace.independent_peak_allocated_cores)} cores`:'Unavailable','Independent event-ledger audit'],['Average utilization',percent(trace.average_capacity_utilization_fraction*100),'Allocated core-seconds over scheduled time envelope'],['Mean delay',`${fmt(trace.mean_delay_seconds_scheduled_tasks,1)} s`,'Scheduled tasks'],['Forecast-eligible tasks',fmt(trace.forecast_eligible_tasks),'Eligible under available replay coverage'],['Fallback decisions',fmt(trace.forecast_fallback_decisions),'Used fallback decision paths'],['Forecast-rescheduled tasks',fmt(trace.decision_counts?.forecast_rescheduled||0),'Actually placed at a forecast-selected alternate start'],['Capacity / constraint violations',fmt((trace.capacity_violations||0)+(trace.task_constraint_violations||0)),'Independent audit']])}</article><article class="detail-panel"><h3>Task outcome mix</h3><div class="outcome-stack"><i style="--share:${trace.completion_rate*100}%;--bar:#80a76b" title="Completed"></i><i style="--share:${trace.deferred_tasks/run.tasks_processed*100}%;--bar:#d2ae73" title="Deferred"></i><i style="--share:${trace.infeasible_tasks/run.tasks_processed*100}%;--bar:#c78273" title="Infeasible"></i></div><div class="outcome-legend"><span><i class="done-dot"></i>Completed ${percent(trace.completion_rate*100)}</span><span><i class="deferred-dot"></i>Deferred ${percent(trace.deferred_tasks/run.tasks_processed*100)}</span><span><i class="infeasible-dot"></i>Infeasible ${percent(trace.infeasible_tasks/run.tasks_processed*100)}</span></div></article><article class="detail-panel"><h3>Task-level records</h3><div class="empty-state">The full task ledger contains over 13 million rows. This dashboard reads aggregate evaluation artifacts and does not load the large ledger into the browser.</div></article>`);
  set('results',header('RESULTS · COMMON POPULATION','Results & comparison','Interpret strategy outcomes with population definitions and the project’s documented limitations.')+`<article class="detail-panel"><h3>Whole-run strategy comparison</h3><p>Each policy completed a different task population. Whole-run emissions are descriptive outcomes and are not a like-for-like carbon comparison.</p>${table(['STRATEGY','COMPLETED','DEFERRED','INFEASIBLE','ENERGY','WHOLE-RUN EMISSIONS','COMMON-SET EMISSIONS','CPU USE'],resultRows())}</article><article class="detail-panel"><h3>Common completed task set</h3>${metricCards([['Shared completed IDs',fmt(common.common_executed_tasks),'Task IDs completed under all three strategies'],['FIFO emissions',`${fmt(common.common_population_observed_emissions_g_co2e?.fifo,4)} g`,'Observed carbon; common IDs'],['Earliest-feasible',`${fmt(common.common_population_observed_emissions_g_co2e?.earliest_feasible,4)} g`,'Observed carbon; common IDs']])}<p>TRACE common-population emissions: <b>${fmt(common.common_population_observed_emissions_g_co2e?.trace,4)} g CO₂e</b>. Difference vs FIFO: <b>${Number(run.common_population_emissions_comparison_vs_fifo?.trace?.percent_difference_vs_fifo||0).toFixed(5)}%</b>. This small observed difference on this shared set does not establish broad superiority or generalize to other workloads or grids.</p></article><article class="detail-panel"><h3>Evidence and limitations</h3><ul><li>Final emissions use observed hourly IN-WE carbon, not forecast values.</li><li>Forecast replay is historical and does not show live forecast availability.</li><li>Energy uses an assumed constant 10 W per CPU core, not measured power.</li><li>Uncertainty intervals act as a risk penalty; formal calibration is not claimed.</li><li>Emissions beyond the observed carbon timeline are not imputed.</li></ul></article>`);
  const audit=data.independent||{}, ledger=Object.entries(audit.strategies||{}), checks=data.cross_check?.strategies||{}, recalculated=data.emissions_recalculation?.strategies||{};
  const auditRows=ledger.map(([key,m])=>[esc(labels[key]),m.passed?'<span class="pill">PASS</span>':'<span class="audit-fail">CHECK</span>',`${fmt(m.row_count)} / ${fmt(m.expected_row_count)}`,fmt(m.unique_id_count),fmt(m.duplicate_id_count),fmt(m.missing_id_count),m.checkpoint_offset_agrees?'Agrees':'Mismatch',checks[key]?.ledger_integrity_passed?'Passed':'Unavailable',recalculated[key]?.passed?'Passed':'Unavailable']);
  const validation=data.validation_summary||{};
  set('validation',header('INDEPENDENT EVIDENCE · READ ONLY','Independent validation','Reconciliation artifacts verify ledger identities, checkpoint offsets, constraints, and emissions independently of the dashboard.')+metricCards([['Ledger rows checked',fmt(audit.workload_rows),'Each of three strategy ledgers'],['Duplicate task IDs',fmt(ledger.reduce((sum,[,m])=>sum+(m.duplicate_id_count||0),0)),'Across independently audited ledgers'],['Missing / unexpected IDs',`${fmt(ledger.reduce((sum,[,m])=>sum+(m.missing_id_count||0)+(m.unexpected_id_count||0),0))}`,'Identity reconciliation'],['Carbon recalculation',data.emissions_recalculation?.completed?'Passed':'Unavailable','Independent row-wise energy and emissions']])+`<article class="detail-panel"><h3>Strategy ledger integrity</h3>${table(['STRATEGY','AUDIT','ROWS','UNIQUE IDS','DUPLICATES','MISSING','CHECKPOINT OFFSET','CROSS-CHECK','EMISSIONS'],auditRows)}</article><div class="detail-grid"><article class="detail-panel"><h3>Input validation</h3>${table(['CHECK','RESULT'],[['Source rows',fmt(validation.total_source_rows)],['Valid rows',fmt(validation.valid_rows)],['Invalid rows',fmt(validation.invalid_rows)],['Duplicate source rows',fmt(validation.duplicate_rows)],['Over CPU-capacity tasks',fmt(validation.tasks_exceeding_cpu_capacity)],['Duration mismatch rows',fmt(validation.duration_mismatch_rows)],['Outside carbon timeline',fmt(validation.tasks_outside_carbon_timeline)],['Carbon observations',fmt(data.emissions_recalculation?.carbon_rows)]])}</article><article class="detail-panel"><h3>Independent emissions recalculation</h3><p>${esc(data.emissions_recalculation?.formula||'Recalculation artifact unavailable.')}</p>${table(['STRATEGY','LEDGER kWh','RECALCULATED kWh','RECALCULATED g CO₂e','MAX TASK DELTA'],Object.entries(recalculated).map(([key,m])=>[esc(labels[key]),fmt(audit.strategies?.[key]?.scheduled_energy_kwh,6),fmt(m.recomputed_energy_kwh,6),fmt(m.recomputed_observed_emissions_g_co2e,3),`${Number(m.maximum_per_task_emissions_difference_g||0).toExponential(1)} g`]))}</article></div><article class="detail-panel"><h3>Validation resources</h3>${table(['METRIC','VALUE'],[['Streaming validation elapsed',validation.elapsed_runtime_seconds?`${fmt(validation.elapsed_runtime_seconds,1)} s`:'Unavailable'],['Streaming validation peak memory',validation.peak_memory_bytes?`${fmt(validation.peak_memory_bytes/1024/1024,1)} MB`:'Unavailable'],['Peak temporary disk',validation.temporary_disk_bytes_peak?`${fmt(validation.temporary_disk_bytes_peak/1024/1024/1024,2)} GB`:'Unavailable'],['Phase 6 process peak RSS',`${fmt(run.peak_rss_bytes/1024/1024,1)} MB`],['All three independent ledgers',ledger.length===3&&ledger.every(([,m])=>m.passed)?'Passed':'Unavailable']])}</article>`);
  set('reproducibility',header('RUN CONFIGURATION · PROVENANCE','Reproducibility','Inspect the inputs, parameters, evidence artifacts, and independent checks for the displayed run.')+`<div class="detail-grid"><article class="detail-panel"><h3>Run metadata</h3>${table(['FIELD','VALUE'],[['Run created (UTC)',esc(cfg.created_utc||'—')],['Zone',esc(cfg.zone||'—')],['Strategies',(cfg.strategies||[]).map(esc).join(', ')],['Workload sampling',esc(cfg.sampling||'—')],['Workload SHA-256',`<code>${esc(cfg.workload_sha256||'Unavailable')}</code>`],['Carbon SHA-256',`<code>${esc(cfg.carbon_sha256||'Unavailable')}</code>`],['Forecast SHA-256',`<code>${esc(cfg.forecast_sha256||'Unavailable')}</code>`]])}</article><article class="detail-panel"><h3>Validation status</h3><p><span class="pill">${run.completed?'Run completed':'Status unavailable'}</span></p><p>Processed ${fmt(run.tasks_processed)} tasks. Independent validation, carbon recalculation, and constraint audits are preserved with the run artifacts.</p><p>Displayed aggregate artifact: <code>${esc(data.artifact)}</code></p></article></div><article class="detail-panel"><h3>Artifact references</h3>${table(['ARTIFACT','PURPOSE'],[['final_evaluation.json','Strategy metrics and population comparisons'],['final_evaluation_by_strategy.csv','Tabular strategy results'],['phase6_run_configuration.json','Input hashes and simulation settings'],['event_run_summary.json','Run completion, runtime, and resource summary'],['independent_validation/','Independent ledger ID and emissions reconciliation'],['results/forecasting/rolling_seasonal_naive_forecasts.csv','Historical forecast replay']])}</article>`);
  const chart=$('#forecast-detail-chart'); if(chart){const carbon=(data.carbon||[]).map(r=>({x:Date.parse(r.datetime),y:Number(r.carbonIntensity),label:r.datetime})).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));const forecastRows=data.forecasts||[];const origin=forecastRows.map(r=>r.forecast_origin_utc).sort().at(-1);const picked=forecastRows.filter(r=>r.forecast_origin_utc===origin).sort((a,b)=>Number(a.horizon_hours)-Number(b.horizon_hours));const prediction=picked.map(r=>({x:Date.parse(r.timestamp_utc),y:Number(r.predicted_carbon_intensity),label:`${r.horizon_hours}h replay forecast`}));const low=picked.map(r=>({x:Date.parse(r.timestamp_utc),y:Number(r.lower_bound)}));const high=picked.map(r=>({x:Date.parse(r.timestamp_utc),y:Number(r.upper_bound)}));chart.innerHTML=svgLineChart([{values:carbon,color:'#75946a'},{values:prediction,color:'#d1a35d',dash:true}],{height:255,bands:[{low,high}]});}
}
function renderEmptyCharts(){for(const selector of ['#strategy-chart','#forecast-chart'])$(selector).innerHTML='<div class="empty-state">Run artifact unavailable. Start the dashboard from the repository root and confirm the Phase 6 output exists.</div>';}

function navigate(view){
  const name=view||'overview';if(!$(`#view-${name}`))return;
  $$('.page-view').forEach(el=>el.classList.toggle('active-view',el.dataset.page===name));
  $$('.nav-link[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===name));
  const link=$(`.nav-link[data-view="${name}"]`);$('#breadcrumb-current').textContent=link?.querySelector('span:last-child')?.textContent||'Dashboard';
  if(name==='forecasting'&&data){const c=$('#forecast-detail-chart');if(c&&c.innerHTML==='')renderPages();}
  if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches)window.scrollTo({top:0,behavior:'smooth'});
}

document.addEventListener('click',event=>{const link=event.target.closest('[data-view]');if(link){event.preventDefault();const view=link.dataset.view;history.replaceState(null,'',`#${view}`);navigate(view);}});
window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)));
$('#comparison-metric').addEventListener('change',renderStrategyChart);
$('#refresh').addEventListener('click',loadData);
$('#global-search').addEventListener('input',event=>{const q=event.target.value.trim().toLowerCase();$$('.panel,.kpi-card,.detail-card,.detail-panel').forEach(el=>el.classList.toggle('search-match',!!q&&el.textContent.toLowerCase().includes(q)));});
loadData().then(()=>navigate(location.hash.slice(1)||'overview'));
