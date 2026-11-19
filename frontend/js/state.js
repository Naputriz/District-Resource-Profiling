/**
 * state.js
 * Single source of truth for mutable application and UI state,
 * including active province/region, loaded districts, active pillar filters,
 * Leaflet layers, and chat history.
 */

export const state = {
  activeProvince: "31",
  activeRegion: null,
  regions: [],
  districts: [],
  districtByCode: new Map(),
  selectedDistrict: null,
  activePillar: null,
  map: null,
  choroplethRenderer: null,
  geojsonLayer: null,
  facilityMarkersLayer: null,
  bufferCirclesLayer: null,
  blankSpotLayer: null,
  legendControl: null,
  chatMessages: [],
  isSimulating: false,
  standardsMetadata: []
};
