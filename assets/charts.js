/* 把 report.json 里的简化图表描述翻译成 ECharts 配置，统一成 kami 画风：
 * 只有一种墨蓝点缀，其余用暖灰；网格细线 #e8e7e1，底线近黑；数字用近黑；字体和正文一样用仓耳今楷。
 * 增速正负条按 A 股习惯红涨绿跌，但用淡一档的浅砖红、浅灰绿；不用双纵轴；不在每个点上标数。 */
(function () {
  const FONT = '"TsangerJinKai02","Source Han Serif SC","Noto Serif CJK SC","Songti SC","STSong",serif';
  const INK = '#141413', OLIVE = '#504e49', STONE = '#6b6a64', GRID = '#e8e7e1', BASE = '#141413';
  const PARCH = '#f5f4ed';
  const CAT = ['#1B365D', '#504e49', '#6b6a64', '#b8b7b0', '#d4d3cd', '#EEF2F7'];
  const ACCENT = '#1B365D', DIM = '#d4d3cd';
  const UP = '#c47a6c', DOWN = '#6b9478';  // 红涨绿跌，淡一档，不刺眼

  function fmt(v, d, unit) {
    if (v === null || v === undefined || isNaN(v)) return '';
    const s = Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
    return s + (unit || '');
  }
  function signed(v, d, unit) {
    const s = fmt(Math.abs(v), d, unit);
    return (v > 0 ? '+' : v < 0 ? '−' : '') + s;
  }
  function tick(v) {  // 坐标轴刻度：整数就不带小数；0.5、0.25 这种按需要的位数
    if (Number.isInteger(v)) return fmt(v, 0);
    const d = Math.abs(v) < 1 ? 2 : 1;
    return fmt(v, (Math.round(v * 10) === v * 10) ? 1 : d);
  }
  function decOf(spec) {
    if (spec.decimals !== undefined) return spec.decimals;
    const all = (spec.series || []).flatMap(s => s.data || []).filter(x => typeof x === 'number');
    return all.some(x => Math.abs(x - Math.round(x)) > 1e-9) ? 1 : 0;
  }
  function inkOn(hex) {  // 色块上的字：深色块用象牙白，浅色块用近黑
    const h = hex.replace('#', '');
    const r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) < 150 ? '#faf9f5' : INK;
  }
  const base = () => ({ animation: false, textStyle: { fontFamily: FONT, color: INK } });
  const lab = (extra) => Object.assign({ color: INK, fontSize: 11, fontFamily: FONT }, extra || {});
  const axisCommon = {
    axisLine: { lineStyle: { color: BASE, width: 0.8 } },
    axisTick: { show: false },
    axisLabel: { color: STONE, fontSize: 10.5, fontFamily: FONT },
    splitLine: { lineStyle: { color: GRID, width: 0.8, type: 'solid' } },
  };
  function legend(series) {
    if (!series || series.length < 2) return undefined;
    return { top: 0, left: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, itemGap: 16,
             textStyle: { color: OLIVE, fontSize: 10.5, fontFamily: FONT } };
  }

  // 竖柱：年份、季度、分组比较
  function bar(spec) {
    const d = decOf(spec), unit = spec.labelUnit || '';
    const multi = spec.series.length > 1;
    const series = spec.series.map((s, si) => ({
      type: 'bar', name: s.name, itemStyle: { color: s.color || CAT[si] },
      data: s.data.map((v, i) => {
        let color = s.color || CAT[si];
        if (!multi && spec.highlight !== undefined) color = (i === spec.highlight) ? ACCENT : DIM;
        if (!multi && (spec.dimIdx || []).includes(i)) color = DIM;
        return { value: v, itemStyle: { color, borderRadius: 2 } };
      }),
      // band：在图上铺一条浅色横带，比如「我们推的区间」
      markArea: (si === 0 && spec.band) ? { silent: true, itemStyle: { color: '#EEF2F7' },
        label: { show: !!spec.band.label, position: 'insideTopLeft', formatter: spec.band.label || '', color: STONE, fontSize: 10, fontFamily: FONT },
        data: [[{ yAxis: spec.band.from }, { yAxis: spec.band.to }]] } : undefined,
      barMaxWidth: multi ? 18 : 28, barGap: '14%', barCategoryGap: multi ? '36%' : '46%',
      label: { show: spec.labels !== false, position: 'top', color: INK, fontSize: 11, fontFamily: FONT,
               formatter: p => fmt(p.value, d, unit) },
    }));
    return Object.assign(base(), {
      legend: legend(spec.series),
      grid: { left: 2, right: 6, top: multi ? 34 : 22, bottom: 2, containLabel: true },
      xAxis: Object.assign({}, axisCommon, { type: 'category', data: spec.categories, splitLine: { show: false },
             axisLabel: Object.assign({}, axisCommon.axisLabel, { interval: 0, color: OLIVE, fontSize: 11 }) }),
      yAxis: Object.assign({}, axisCommon, { type: 'value', axisLine: { show: false },
             axisLabel: Object.assign({}, axisCommon.axisLabel, { formatter: tick }),
             min: spec.min, max: spec.max }),
      series,
    });
  }

  // 横条：排名、份额、规模（从上到下按给的顺序）
  function barh(spec) {
    const d = decOf(spec), unit = spec.labelUnit || '';
    const cats = spec.categories.slice().reverse();
    const s0 = spec.series[0];
    const vals = s0.data.slice().reverse();
    const tags = (spec.tags || []).slice().reverse();
    const hl = spec.highlightIf || null;
    const hlIdx = (spec.highlightIdx || []).map(i => spec.categories.length - 1 - i);
    const data = vals.map((v, i) => {
      let color = s0.color || ACCENT;
      if (hl) {
        const ok = (hl.gte !== undefined && v >= hl.gte) || (hl.lte !== undefined && v <= hl.lte);
        color = ok ? ACCENT : DIM;
      }
      if (hlIdx.length) color = hlIdx.includes(i) ? ACCENT : DIM;
      return { value: v, itemStyle: { color, borderRadius: 2 } };
    });
    return Object.assign(base(), {
      grid: { left: 2, right: spec.rightPad || 84, top: 4, bottom: 2, containLabel: true },
      xAxis: Object.assign({}, axisCommon, { type: 'value', show: spec.showAxis === true, max: spec.max, min: 0,
             splitLine: { show: false } }),
      yAxis: Object.assign({}, axisCommon, { type: 'category', data: cats,
             axisLine: { show: true, lineStyle: { color: BASE, width: 0.8 } },
             axisLabel: Object.assign({}, axisCommon.axisLabel, { color: INK, fontSize: 11 }) }),
      series: [{
        type: 'bar', data, barMaxWidth: 13, barCategoryGap: '40%',
        label: { show: true, position: 'right', color: INK, fontSize: 11, fontFamily: FONT,
                 formatter: p => fmt(p.value, d, unit) + (tags[p.dataIndex] ? '   ' + tags[p.dataIndex] : '') },
      }],
    });
  }

  // 正负条：增速、变化。红涨绿跌（淡色）；另有 +/− 号。
  // highlightIdx / refIdx：费用、库存这类「涨了不是好事」的，改成强调模式
  function diverge(spec) {
    const d = decOf(spec), unit = spec.labelUnit === undefined ? '%' : spec.labelUnit;
    const cats = spec.categories.slice().reverse();
    const vals = spec.series[0].data.slice().reverse();
    const maxPos = Math.max(0, ...vals), minNeg = Math.min(0, ...vals);
    const span = Math.max(maxPos, -minNeg);
    const xmax = maxPos > 0 ? maxPos + span * 0.42 : span * 0.15;
    const xmin = minNeg < 0 ? minNeg - span * 0.42 : 0;
    const n = spec.categories.length;
    const hi = (spec.highlightIdx || []).map(i => n - 1 - i);
    const ref = spec.refIdx !== undefined ? n - 1 - spec.refIdx : -1;
    const data = vals.map((v, i) => {
      let color = v >= 0 ? UP : DOWN;
      if (hi.length || ref >= 0) color = hi.includes(i) ? ACCENT : (i === ref ? OLIVE : DIM);
      return { value: v, itemStyle: { color, borderRadius: 2 }, label: { position: v >= 0 ? 'right' : 'left' } };
    });
    return Object.assign(base(), {
      grid: { left: 2, right: 6, top: 4, bottom: 2, containLabel: true },
      xAxis: Object.assign({}, axisCommon, { type: 'value', show: false,
             min: spec.min !== undefined ? spec.min : xmin, max: spec.max !== undefined ? spec.max : xmax }),
      yAxis: Object.assign({}, axisCommon, { type: 'category', data: cats,
             axisLine: { show: true, lineStyle: { color: BASE, width: 0.8 } },
             axisLabel: Object.assign({}, axisCommon.axisLabel, { color: INK, fontSize: 11 }) }),
      series: [{ type: 'bar', data, barMaxWidth: 13, barCategoryGap: '40%',
                 label: { show: true, color: INK, fontSize: 11, fontFamily: FONT, formatter: p => signed(p.value, d, unit) } }],
    });
  }

  // 折线：趋势
  function line(spec) {
    const d = decOf(spec), unit = spec.labelUnit || '';
    const multi = spec.series.length > 1;
    const series = spec.series.map((s, si) => {
      const c = s.color || CAT[si];
      return {
        type: 'line', name: s.name, data: s.data, smooth: false,
        lineStyle: { width: 2, color: c }, itemStyle: { color: c, borderColor: PARCH, borderWidth: 1.5 },
        symbol: 'circle', symbolSize: 7,
        label: { show: true, color: INK, fontSize: 11, fontFamily: FONT, position: 'top',
                 formatter: p => (spec.labelAll || p.dataIndex === s.data.length - 1 || p.dataIndex === 0) ? fmt(p.value, d, unit) : '' },
        areaStyle: (!multi && spec.area) ? { color: '#EEF2F7', opacity: 0.9 } : undefined,
        // band：浅色横带，比如 ROE 的理想区 10%–20%（和柱状图的 band 一样）
        markArea: (si === 0 && spec.band) ? { silent: true, itemStyle: { color: '#EEF2F7' },
          label: { show: !!spec.band.label, position: 'insideTopLeft', formatter: spec.band.label || '', color: STONE, fontSize: 10, fontFamily: FONT },
          data: [[{ yAxis: spec.band.from }, { yAxis: spec.band.to }]] } : undefined,
      };
    });
    return Object.assign(base(), {
      legend: legend(spec.series),
      grid: { left: 2, right: 16, top: multi ? 34 : 24, bottom: 2, containLabel: true },
      xAxis: Object.assign({}, axisCommon, { type: 'category', data: spec.categories, boundaryGap: true, splitLine: { show: false },
             axisLabel: Object.assign({}, axisCommon.axisLabel, { color: OLIVE, fontSize: 11 }) }),
      yAxis: Object.assign({}, axisCommon, { type: 'value', axisLine: { show: false }, scale: spec.scale !== false,
             min: spec.min, max: spec.max, axisLabel: Object.assign({}, axisCommon.axisLabel, { formatter: tick }) }),
      series,
    });
  }

  // 环形图：构成（最多 6 块）。kami 的做法：图例放右边，写百分比和名字，环上不贴标签。
  // 圆心和半径按容器实际宽高算（放进半栏也不会被切）
  function donut(spec, box) {
    const d = spec.decimals !== undefined ? spec.decimals : 1;
    const s0 = spec.series[0];
    const total = s0.data.reduce((a, b) => a + b, 0);
    const pct = {};
    spec.categories.forEach((c, i) => { pct[c] = s0.data[i] / total * 100; });
    const PIE = ['#1B365D', '#504e49', '#6b6a64', '#9a988f', '#b8b7b0', '#d4d3cd'];
    const data = spec.categories.map((c, i) => ({ name: c, value: s0.data[i],
      itemStyle: { color: (spec.colors && spec.colors[i]) || PIE[i], borderColor: PARCH, borderWidth: 1.5 } }));
    const w = (box && box.w) || 320, h = (box && box.h) || 230;
    const rOut = Math.max(40, Math.min(h / 2 - 8, w * 0.46 / 2 - 4));
    const cx = 4 + rOut, cy = h / 2;
    const center = spec.center || null;
    return Object.assign(base(), {
      title: center ? { text: center.value, subtext: center.label, left: cx, top: cy - 22, textAlign: 'center',
        textStyle: { fontSize: rOut > 70 ? 17 : 14, fontWeight: 500, color: ACCENT, fontFamily: FONT },
        subtextStyle: { fontSize: 9.5, color: STONE, fontFamily: FONT }, itemGap: 3 } : undefined,
      legend: { orient: 'vertical', left: cx + rOut + 18, top: 'middle', icon: 'roundRect', itemWidth: 10, itemHeight: 10, itemGap: 9,
        itemStyle: { borderWidth: 0 },
        formatter: name => '{p|' + fmt(pct[name], d, '%') + '}{n|' + name + '}',
        textStyle: { fontFamily: FONT, rich: {
          p: { fontSize: 11, color: INK, fontWeight: 500, width: 44, fontFamily: FONT },
          n: { fontSize: 10.5, color: OLIVE, fontFamily: FONT } } } },
      series: [{
        type: 'pie', radius: [rOut * 0.64, rOut], center: [cx, cy], data, startAngle: 90,
        label: { show: false }, labelLine: { show: false },
      }],
    });
  }

  // 100% 堆叠横条：两年结构对比（如国内/海外）
  function stack100(spec) {
    const cats = spec.categories.slice().reverse();
    const n = spec.series.length;
    const colors = spec.series.map((s, si) => s.color || (si === 0 ? ACCENT : ['#b8b7b0', '#d4d3cd', '#6b6a64'][si - 1] || DIM));
    const series = spec.series.map((s, si) => ({
      type: 'bar', name: s.name, stack: 'all', barMaxWidth: 22, barCategoryGap: '42%',
      data: s.data.slice().reverse(),
      itemStyle: { color: colors[si], borderColor: PARCH, borderWidth: 1,
                   borderRadius: si === 0 ? [2, 0, 0, 2] : si === n - 1 ? [0, 2, 2, 0] : 0 },
      label: { show: true, position: 'inside', color: inkOn(colors[si]), fontSize: 11, fontFamily: FONT,
               formatter: p => p.value >= 9 ? s.name + ' ' + fmt(p.value, 1, '%') : '' },
    }));
    return Object.assign(base(), {
      legend: legend(spec.series),
      grid: { left: 2, right: 6, top: 30, bottom: 2, containLabel: true },
      xAxis: Object.assign({}, axisCommon, { type: 'value', max: 100, show: false }),
      yAxis: Object.assign({}, axisCommon, { type: 'category', data: cats, axisLine: { show: false },
             axisLabel: Object.assign({}, axisCommon.axisLabel, { color: INK, fontSize: 11 }) }),
      series,
    });
  }

  const MAKERS = { bar, barh, diverge, line, donut, stack100 };

  window.renderCharts = function (specs) {
    const pending = [];
    specs.forEach(spec => {
      const el = document.getElementById(spec.id);
      if (!el) return;
      const make = MAKERS[spec.kind];
      if (!make) { el.innerHTML = '<div style="color:#141413;font-size:10pt">未知图表类型：' + spec.kind + '</div>'; return; }
      const chart = echarts.init(el, null, { renderer: 'svg' });
      pending.push(new Promise(res => { chart.on('finished', res); setTimeout(res, 1500); }));
      chart.setOption(make(spec, { w: el.clientWidth, h: el.clientHeight }));
    });
    return Promise.all(pending);
  };
})();
