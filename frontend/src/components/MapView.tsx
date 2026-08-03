import { useRef, useEffect, useCallback } from 'react'
import {
  Map as MLMap,
  Marker as MLMarker,
  Popup,
  NavigationControl,
  type GeoJSONSource,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { FeatureCollection, Feature, Point } from 'geojson'
import { useLocale } from '../i18n/LocaleContext.jsx'
import { formatCurrency } from '../i18n/format.js'
import { linkIdForProperty } from '../routes/propertyPaths.js'
import { combinedScoreForListingType, formatScorePercent } from '../utils/scores.js'
import { decisioningPrice } from '../utils/primaryListing.js'
import type { Property } from '../api.js'
import type { TFunction } from '../i18n/LocaleContext.jsx'

/** A property guaranteed to have numeric coordinates (post-filter). */
type LocatedProperty = Property & { lat: number; lon: number }

function scoreColor(v: number | null | undefined): string {
  if (v == null) return '#6b7280'  // grey for no score
  if (v >= 0.7) return '#10b981'  // green
  if (v >= 0.4) return '#f59e0b'  // yellow
  return '#ef4444'                 // red
}

function propertyLinkId(p: Property): string | null {
  return linkIdForProperty(p) || (p?.id != null ? String(p.id) : null)
}

function hasCoords(p: Property): p is LocatedProperty {
  return p.lat != null && p.lon != null
}

export interface MapViewProps {
  properties: Property[]
  listingType?: string
  onSelectProperty?: (id: string) => void
  onBboxChange?: (bbox: string) => void
  compareMode?: boolean
  selectedIds?: string[]
  onToggleCompare?: (id: string) => void
}

export default function MapView({
  properties,
  listingType = 'both',
  onSelectProperty,
  onBboxChange,
  compareMode = false,
  selectedIds = [],
  onToggleCompare,
}: MapViewProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MLMap | null>(null)
  const markersRef = useRef<MLMarker[]>([])
  const layersReadyRef = useRef(false)
  // True once the map has fired `load` (style parsed, safe to add sources/layers/
  // markers). Used instead of `isStyleLoaded()`, which under maplibre-gl v6 keeps
  // returning false while raster tiles are still pending.
  const loadedRef = useRef(false)
  const { t, locale } = useLocale()

  const compareModeRef = useRef(compareMode)
  const selectedIdsRef = useRef(selectedIds)
  const onToggleCompareRef = useRef(onToggleCompare)
  const onSelectPropertyRef = useRef(onSelectProperty)
  const onBboxChangeRef = useRef(onBboxChange)
  const listingTypeRef = useRef(listingType)
  const propertiesRef = useRef(properties)
  const tRef = useRef<TFunction>(t)
  const localeRef = useRef(locale)
  const updateMarkersRef = useRef<((map: MLMap, props: Property[]) => void) | null>(null)

  useEffect(() => { compareModeRef.current = compareMode }, [compareMode])
  useEffect(() => { selectedIdsRef.current = selectedIds }, [selectedIds])
  useEffect(() => { onToggleCompareRef.current = onToggleCompare }, [onToggleCompare])
  useEffect(() => { onSelectPropertyRef.current = onSelectProperty }, [onSelectProperty])
  useEffect(() => { onBboxChangeRef.current = onBboxChange }, [onBboxChange])
  useEffect(() => { listingTypeRef.current = listingType }, [listingType])
  useEffect(() => { propertiesRef.current = properties }, [properties])
  useEffect(() => { tRef.current = t }, [t])
  useEffect(() => { localeRef.current = locale }, [locale])

  const clearCompareMarkers = useCallback(() => {
    markersRef.current.forEach((m) => m.remove())
    markersRef.current = []
  }, [])

  const syncCompareMarkers = useCallback((map: MLMap, props: Property[]) => {
    clearCompareMarkers()
    if (!compareModeRef.current) return

    const selectedSet = new Set((selectedIdsRef.current || []).map(String))
    const translate = tRef.current

    props
      .filter(hasCoords)
      .forEach((p) => {
        const linkId = propertyLinkId(p)
        if (!linkId) return

        const selected = selectedSet.has(String(linkId))
        const el = document.createElement('button')
        el.type = 'button'
        el.className = `map-compare-hit${selected ? ' map-compare-hit--selected' : ''}`
        el.dataset.testid = `map-compare-select-${linkId}`
        el.setAttribute('aria-pressed', selected ? 'true' : 'false')
        el.setAttribute(
          'aria-label',
          selected
            ? translate('properties.removeFromComparison')
            : translate('properties.selectForComparison'),
        )
        el.addEventListener('click', (e) => {
          e.preventDefault()
          e.stopPropagation()
          onToggleCompareRef.current?.(linkId)
        })

        const marker = new MLMarker({ element: el, anchor: 'center' })
          .setLngLat([p.lon, p.lat])
          .addTo(map)
        markersRef.current.push(marker)
      })
  }, [clearCompareMarkers])

  const buildGeojson = useCallback((props: Property[]): FeatureCollection<Point> => {
    const selectedSet = new Set((selectedIdsRef.current || []).map(String))
    const type = listingTypeRef.current
    const translate = tRef.current

    return {
      type: 'FeatureCollection',
      features: props
        .filter(hasCoords)
        .map((p): Feature<Point> => {
          const displayScore = combinedScoreForListingType(p, type)
          const linkId = propertyLinkId(p)
          return {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
            properties: {
              id: p.id,
              link_id: linkId,
              selected: linkId && selectedSet.has(String(linkId)) ? 1 : 0,
              title: p.title || translate('common.untitled'),
              price: decisioningPrice(p),
              combined_score: displayScore,
              neighborhood_name: p.neighborhood_name,
              bedrooms: p.bedrooms,
              area_m2: p.area_m2,
            },
          }
        }),
    }
  }, [])

  const ensureLayers = useCallback((map: MLMap, sourceId: string) => {
    if (layersReadyRef.current) return

    // Cluster circles
    map.addLayer({
      id: 'clusters',
      type: 'circle',
      source: sourceId,
      filter: ['has', 'point_count'],
      paint: {
        'circle-color': [
          'step', ['get', 'point_count'],
          '#6366f1', 10,
          '#8b5cf6', 30,
          '#a855f7', 70,
          '#c026d3',
        ],
        'circle-radius': [
          'step', ['get', 'point_count'],
          16, 10,
          22, 30,
          28, 70,
          34,
        ],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#1e1b4b',
      },
    })

    // Cluster count labels
    map.addLayer({
      id: 'cluster-count',
      type: 'symbol',
      source: sourceId,
      filter: ['has', 'point_count'],
      layout: {
        'text-field': '{point_count_abbreviated}',
        'text-font': ['Noto Sans Regular'],
        'text-size': 12,
      },
      paint: {
        'text-color': '#ffffff',
      },
    })

    // Unclustered points — coloured markers; selected gets thicker white stroke
    map.addLayer({
      id: 'unclustered-point',
      type: 'circle',
      source: sourceId,
      filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-color': [
          'case',
          ['>=', ['get', 'combined_score'], 0.7], '#10b981',
          ['>=', ['get', 'combined_score'], 0.4], '#f59e0b',
          ['has', 'combined_score'], '#ef4444',
          '#6b7280',
        ],
        'circle-radius': [
          'case',
          ['==', ['get', 'selected'], 1], 10,
          8,
        ],
        'circle-stroke-width': [
          'case',
          ['==', ['get', 'selected'], 1], 4,
          2,
        ],
        'circle-stroke-color': [
          'case',
          ['==', ['get', 'selected'], 1], '#ffffff',
          '#1e1b4b',
        ],
      },
    })

    const popup = new Popup({
      offset: 12,
      maxWidth: '280px',
      className: 'map-popup',
    })

    map.on('click', 'unclustered-point', (e: MapLayerMouseEvent) => {
      const feat = e.features?.[0]
      if (!feat) return
      const featProps = feat.properties
      if (!featProps) return
      const linkId = featProps.link_id != null && featProps.link_id !== ''
        ? String(featProps.link_id)
        : (featProps.id != null ? String(featProps.id) : null)

      if (compareModeRef.current) {
        popup.remove()
        if (linkId) onToggleCompareRef.current?.(linkId)
        return
      }

      const coords = (feat.geometry as Point).coordinates.slice() as [number, number]
      const translate = tRef.current
      const loc = localeRef.current
      const score = featProps.combined_score != null
        ? formatScorePercent(featProps.combined_score)
        : translate('common.emDash')

      const container = document.createElement('div')
      container.style.cssText = 'padding: 4px 0; font-size: 13px;'

      const titleDiv = document.createElement('div')
      titleDiv.style.cssText = 'font-weight: 600; margin-bottom: 4px; line-height: 1.3;'
      titleDiv.textContent = featProps.title
      container.appendChild(titleDiv)

      const priceDiv = document.createElement('div')
      priceDiv.style.cssText = 'font-size: 15px; font-weight: 700; color: var(--accent, #6366f1); margin-bottom: 4px;'
      priceDiv.textContent = formatCurrency(featProps.price, loc)
      container.appendChild(priceDiv)

      const detailsDiv = document.createElement('div')
      detailsDiv.style.cssText = 'color: var(--text-muted, #9ca3af); font-size: 11px; margin-bottom: 6px;'
      const beds = featProps.bedrooms ? `· ${translate('common.bedsShort', { n: featProps.bedrooms })}` : ''
      const area = featProps.area_m2 ? `· ${translate('common.areaM2Compact', { n: featProps.area_m2 })}` : ''
      detailsDiv.textContent = `${featProps.neighborhood_name || ''} ${beds} ${area}`.trim()
      container.appendChild(detailsDiv)

      const scoreDiv = document.createElement('div')
      scoreDiv.style.cssText = 'font-size: 12px; margin-bottom: 6px;'
      const scoreLabel = translate('map.score', { value: '' }).replace(/\s*$/, '')
      scoreDiv.innerHTML = `${scoreLabel} <strong style="color: ${scoreColor(featProps.combined_score)}">${score}</strong>`
      container.appendChild(scoreDiv)

      const btn = document.createElement('button')
      btn.className = 'map-view-btn'
      btn.dataset.id = featProps.id
      btn.style.cssText = 'background: var(--accent, #6366f1); color: white; border: none; padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600; width: 100%;'
      btn.textContent = translate('map.viewDetails')
      btn.addEventListener('click', () => {
        onSelectPropertyRef.current?.(featProps.id)
        popup.remove()
      })
      container.appendChild(btn)

      popup.setLngLat(coords).setDOMContent(container).addTo(map)
    })

    map.on('mouseenter', 'unclustered-point', () => {
      map.getCanvas().style.cursor = 'pointer'
    })
    map.on('mouseleave', 'unclustered-point', () => {
      map.getCanvas().style.cursor = ''
    })

    map.on('click', 'clusters', (e: MapLayerMouseEvent) => {
      const features = map.queryRenderedFeatures(e.point, { layers: ['clusters'] })
      const clusterId = features[0]?.properties?.cluster_id
      const source = map.getSource(sourceId) as GeoJSONSource | undefined
      source?.getClusterExpansionZoom(clusterId)
        .then((zoom) => {
          map.easeTo({ zoom, center: e.lngLat })
        })
        .catch((err) => {
          console.error('cluster_expand_error', err)
        })
    })

    layersReadyRef.current = true
  }, [])

  const updateMarkers = useCallback((map: MLMap, props: Property[]) => {
    const geojson = buildGeojson(props)
    const sourceId = 'properties'

    const existing = map.getSource(sourceId) as GeoJSONSource | undefined
    if (existing) {
      existing.setData(geojson)
    } else {
      map.addSource(sourceId, {
        type: 'geojson',
        data: geojson,
        cluster: true,
        clusterMaxZoom: 16,
        clusterRadius: 50,
      })
      ensureLayers(map, sourceId)
    }

    syncCompareMarkers(map, props)
  }, [buildGeojson, ensureLayers, syncCompareMarkers])

  useEffect(() => {
    updateMarkersRef.current = updateMarkers
  }, [updateMarkers])

  // Initialize map
  useEffect(() => {
    const container = mapContainer.current
    if (!container || mapRef.current) return

    const style: StyleSpecification = {
      version: 8,
      sources: {
        osm: {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: '&copy; OpenStreetMap contributors',
          maxzoom: 19,
        },
      },
      layers: [{
        id: 'osm',
        type: 'raster',
        source: 'osm',
      }],
    }

    const map = new MLMap({
      container,
      style,
      center: [-43.94, -19.92],  // Belo Horizonte
      zoom: 13,
    })

    map.addControl(new NavigationControl(), 'top-right')

    map.on('load', () => {
      loadedRef.current = true
      updateMarkersRef.current?.(map, propertiesRef.current || [])
      // Deterministic readiness signal for tests / consumers: the style has
      // loaded and the first frame rendered. Previously keyed off `idle`, but
      // maplibre-gl v6 no longer fires `idle` while raster tiles stay pending
      // (offline, or when the OSM tile host blocks automated requests), which
      // hung the signal forever. `load` does not depend on tile fetch success
      // and still guarantees `isStyleLoaded()` is true for marker syncing.
      mapContainer.current?.setAttribute('data-map-ready', 'true')
    })

    map.on('moveend', () => {
      const b = map.getBounds()
      const bboxStr = `${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`
      onBboxChangeRef.current?.(bboxStr)
    })

    mapRef.current = map

    return () => {
      clearCompareMarkers()
      map.remove()
      mapRef.current = null
      layersReadyRef.current = false
      loadedRef.current = false
    }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Update markers when properties / compare selection change.
  // Gate on the `load` event (via loadedRef), not `isStyleLoaded()`: the latter
  // stays false under maplibre-gl v6 while raster tiles are pending, and the old
  // `once('idle')` fallback then never fired when tiles fail to load (offline, or
  // OSM blocking automated requests) — dropping the sync forever (BIN-189/#33).
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const run = () => updateMarkers(map, properties || [])
    if (loadedRef.current) {
      run()
      return
    }
    map.once('load', run)
    return () => { map.off('load', run) }
  }, [properties, listingType, compareMode, selectedIds, updateMarkers])

  return (
    <div
      ref={mapContainer}
      className="map-container"
      data-testid="map-view"
      style={{ width: '100%', height: 'calc(100vh - 200px)', borderRadius: 8, overflow: 'hidden' }}
    />
  )
}
