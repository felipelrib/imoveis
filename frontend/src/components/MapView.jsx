import { useRef, useEffect, useCallback } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

function scoreColor(v) {
  if (v == null) return '#6b7280'  // grey for no score
  if (v >= 0.7) return '#10b981'  // green
  if (v >= 0.4) return '#f59e0b'  // yellow
  return '#ef4444'                 // red
}

function formatPrice(p) {
  if (!p) return '—'
  return 'R$ ' + Number(p).toLocaleString('pt-BR')
}

export default function MapView({ properties, onSelectProperty, onBboxChange }) {
  const mapContainer = useRef(null)
  const mapRef = useRef(null)
  const markersRef = useRef([])

  const updateMarkers = useCallback((map, props) => {
    // Remove old markers
    markersRef.current.forEach(m => m.remove())
    markersRef.current = []

    const geojson = {
      type: 'FeatureCollection',
      features: props
        .filter(p => p.lat != null && p.lon != null)
        .map(p => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
          properties: {
            id: p.id,
            title: p.title || 'Sem titulo',
            price: p.price,
            combined_score: p.combined_score,
            neighborhood_name: p.neighborhood_name,
            bedrooms: p.bedrooms,
            area_m2: p.area_m2,
          },
        })),
    }

    // Update or create source
    const sourceId = 'properties'
    if (map.getSource(sourceId)) {
      map.getSource(sourceId).setData(geojson)
    } else {
      map.addSource(sourceId, {
        type: 'geojson',
        data: geojson,
        cluster: true,
        clusterMaxZoom: 16,
        clusterRadius: 50,
      })

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

      // Unclustered points — coloured markers
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
          'circle-radius': 8,
          'circle-stroke-width': 2,
          'circle-stroke-color': '#1e1b4b',
        },
      })

      // Popup for unclustered points
      const popup = new maplibregl.Popup({
        offset: 12,
        maxWidth: '280px',
        className: 'map-popup',
      })

      map.on('click', 'unclustered-point', (e) => {
        const props = e.features[0].properties
        const coords = e.features[0].geometry.coordinates.slice()
        const score = props.combined_score != null
          ? (props.combined_score * 100).toFixed(0)
          : '—'

        const popupHtml = `
          <div style="padding: 4px 0; font-size: 13px;">
            <div style="font-weight: 600; margin-bottom: 4px; line-height: 1.3;">${props.title}</div>
            <div style="font-size: 15px; font-weight: 700; color: var(--accent, #6366f1); margin-bottom: 4px;">${formatPrice(props.price)}</div>
            <div style="color: var(--text-muted, #9ca3af); font-size: 11px; margin-bottom: 6px;">
              ${props.neighborhood_name || ''} ${props.bedrooms ? '· ' + props.bedrooms + ' beds' : ''} ${props.area_m2 ? '· ' + props.area_m2 + 'm²' : ''}
            </div>
            <div style="font-size: 12px; margin-bottom: 6px;">Score: <strong style="color: ${scoreColor(props.combined_score)}">${score}</strong></div>
            <button class="map-view-btn" data-id="${props.id}" style="
              background: var(--accent, #6366f1); color: white; border: none;
              padding: 5px 12px; border-radius: 6px; cursor: pointer;
              font-size: 12px; font-weight: 600; width: 100%;
            ">View Details</button>
          </div>
        `
        popup.setLngLat(coords).setHTML(popupHtml).addTo(map)

        // Attach click handler to View Details button
        setTimeout(() => {
          const btn = map.getContainer().querySelector('.map-view-btn')
          if (btn) {
            btn.addEventListener('click', () => {
              onSelectProperty(btn.dataset.id)
              popup.remove()
            })
          }
        }, 0)
      })

      // Hover cursor
      map.on('mouseenter', 'unclustered-point', () => {
        map.getCanvas().style.cursor = 'pointer'
      })
      map.on('mouseleave', 'unclustered-point', () => {
        map.getCanvas().style.cursor = ''
      })

      // Click on cluster — zoom in
      map.on('click', 'clusters', (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: ['clusters'] })
        const clusterId = features[0].properties.cluster_id
        map.getSource(sourceId).getClusterExpansionZoom(clusterId, (err, zoom) => {
          if (err) return
          map.easeTo({ zoom, center: e.lngLat })
        })
      })
    }
  }, [onSelectProperty])

  // Initialize map
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: {
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
      },
      center: [-43.94, -19.92],  // Belo Horizonte
      zoom: 13,
    })

    map.addControl(new maplibregl.NavigationControl(), 'top-right')

    map.on('load', () => {
      if (properties && properties.length > 0) {
        updateMarkers(map, properties)
      }
    })

    // Emit bbox on moveend
    map.on('moveend', () => {
      const b = map.getBounds()
      const bboxStr = `${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`
      if (onBboxChange) onBboxChange(bboxStr)
    })

    mapRef.current = map

    return () => {
      markersRef.current.forEach(m => m.remove())
      map.remove()
      mapRef.current = null
    }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Update markers when properties change
  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return
    updateMarkers(map, properties || [])
  }, [properties, updateMarkers])

  return (
    <div
      ref={mapContainer}
      className="map-container"
      style={{ width: '100%', height: 'calc(100vh - 200px)', borderRadius: 8, overflow: 'hidden' }}
    />
  )
}
