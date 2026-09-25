function mapFeatureName(feature) {
  return String(feature?.properties?.name || '').trim();
}

function mapLayerSignature(features) {
  return (features || [])
    .filter(f => f?.geometry?.type === 'Point')
    .map(f => {
      const coords = f.geometry?.coordinates || [];
      const name = mapFeatureName(f).toLowerCase();
      const lat = Number(coords[1] || 0).toFixed(6);
      const lng = Number(coords[0] || 0).toFixed(6);
      return `${name}|${lat}|${lng}`;
    })
    .sort()
    .slice(0, 80)
    .join('||');
}

function mapLayerPointKeys(features) {
  return new Set((features || [])
    .filter(f => f?.geometry?.type === 'Point')
    .map(f => {
      const coords = f.geometry?.coordinates || [];
      const name = mapFeatureName(f).toLowerCase();
      const lat = Number(coords[1] || 0).toFixed(6);
      const lng = Number(coords[0] || 0).toFixed(6);
      return `${name}|${lat}|${lng}`;
    })
    .filter(Boolean));
}

function mapLayerOverlapsImported(layer, importedPointSets) {
  const keys = mapLayerPointKeys(layer.features);
  if (!keys.size) return false;
  for (const importedKeys of importedPointSets) {
    if (!importedKeys?.size) continue;
    let common = 0;
    keys.forEach(key => { if (importedKeys.has(key)) common += 1; });
    const overlap = common / Math.min(keys.size, importedKeys.size);
    if (overlap >= 0.8) return true;
  }
  return false;
}

const feature = { type: 'Feature', properties: { name: 'CAM 01' }, geometry: { type: 'Point', coordinates: [-36.1, -9.1] } };
const importedLayers = [{ id: 'imported:a', layerId: 'a', features: [feature], count: 1 }];
const importedSignatures = new Set(importedLayers.map(layer => mapLayerSignature(layer.features)).filter(Boolean));
const importedLayerIds = new Set(importedLayers.map(layer => layer.layerId).filter(Boolean));
const importedPointSets = importedLayers.map(layer => mapLayerPointKeys(layer.features)).filter(set => set.size);
const generatedLayers = [
  { id: 'generated:dup-by-source', sourceLayerId: 'a', features: [feature], count: 1 },
  { id: 'generated:dup-by-signature', sourceLayerId: '', features: [feature], count: 1 },
  { id: 'generated:dup-by-overlap', sourceLayerId: '', features: [feature, { ...feature, properties: { name: 'CAM EXTRA' } }], count: 2 },
  { id: 'generated:unique', sourceLayerId: '', features: [{ ...feature, properties: { name: 'CAM 02' } }], count: 1 },
].filter(layer =>
  !importedLayerIds.has(layer.sourceLayerId)
  && !importedSignatures.has(mapLayerSignature(layer.features))
  && !mapLayerOverlapsImported(layer, importedPointSets)
);
const results = [
  ...importedLayers.filter(r => r.count > 0),
  ...generatedLayers.filter(r => r.count > 0),
];

if (results.map(r => r.id).join(',') !== 'imported:a,generated:unique') {
  console.error(results);
  process.exit(1);
}
console.log('ok imported layer wins over duplicate generated layer');
