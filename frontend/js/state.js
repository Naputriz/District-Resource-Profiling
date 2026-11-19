/**
 * state.js
 * Single source of truth for mutable application and UI state,
 * including loaded districts, active pillar filters, Leaflet layers, and chat history.
 */

export const state = {
  districts: [],
  selectedDistrict: null,
  activePillar: null,
  map: null,
  geojsonLayer: null,
  facilityMarkersLayer: null,
  bufferCirclesLayer: null,
  blankSpotLayer: null,
  legendControl: null,
  chatMessages: [],
  isSimulating: false,
  standardsMetadata: []
};
