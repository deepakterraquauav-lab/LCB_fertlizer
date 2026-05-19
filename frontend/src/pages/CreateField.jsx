import { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet-draw/dist/leaflet.draw.css';
import 'leaflet-draw';
import Swal from 'sweetalert2';
import { saveField, parseCoordinates } from '../utils/api';
import { kml } from '@mapbox/togeojson';
import './CreateField.css';

// Fix for leaflet-draw geodesicArea
if (L.GeometryUtil && !L.GeometryUtil.geodesicArea) {
    L.GeometryUtil.geodesicArea = function (latLngs) {
        const pointsCount = latLngs.length;
        let area = 0.0;
        const d2r = Math.PI / 180;

        if (pointsCount > 2) {
            for (let i = 0; i < pointsCount; i++) {
                const p1 = latLngs[i];
                const p2 = latLngs[(i + 1) % pointsCount];
                area += ((p2.lng - p1.lng) * d2r) *
                    (2 + Math.sin(p1.lat * d2r) + Math.sin(p2.lat * d2r));
            }
            area = area * 6378137.0 * 6378137.0 / 2.0;
        }
        return Math.abs(area);
    };
}

// Fix for leaflet-draw readableArea error (type is not defined)
if (L.GeometryUtil) {
    L.GeometryUtil.readableArea = function (area, isMetric, precision) {
        if (typeof precision === 'undefined') precision = 2;
        if (typeof isMetric === 'undefined') isMetric = true;

        var areaStr;
        if (isMetric) {
            if (area >= 10000) {
                areaStr = (area / 10000).toFixed(precision) + ' ha';
            } else {
                areaStr = area.toFixed(precision) + ' m²';
            }
        } else {
            area /= 0.836127; // sq yards
            if (area >= 3097600) { // sq miles
                areaStr = (area / 3097600).toFixed(precision) + ' mi²';
            } else if (area >= 4840) { // acres
                areaStr = (area / 4840).toFixed(precision) + ' acres';
            } else {
                areaStr = Math.ceil(area) + ' yd²';
            }
        }
        return areaStr;
    };
}

function CreateField() {
    const navigate = useNavigate();
    const mapRef = useRef(null);
    const mapInstanceRef = useRef(null);
    const drawnItemsRef = useRef(null);
    const currentLayerRef = useRef(null);
    const drawHandlerRef = useRef(null);
    const editHandlerRef = useRef(null);

    const [showOverlay, setShowOverlay] = useState(false);
    const [showToolbar, setShowToolbar] = useState(true);
    const [showFieldInfo, setShowFieldInfo] = useState(false);
    const [fieldInfo, setFieldInfo] = useState({ area: '-', type: '-', perimeter: '-' });
    const [activeTool, setActiveTool] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [isSearching, setIsSearching] = useState(false);
    const [toolbarPos, setToolbarPos] = useState({ x: null, y: null });
    const [isDraggingToolbar, setIsDraggingToolbar] = useState(false);
    const dragOffsetRef = useRef({ x: 0, y: 0 });
    const toolbarRef = useRef(null);
    const searchMarkerRef = useRef(null); // Ref for search marker

    // Initialize map
    useEffect(() => {
        if (!mapRef.current || mapInstanceRef.current) return;

        const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles &copy; Esri',
            maxZoom: 24,
            maxNativeZoom: 18,
        });

        const streetLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 24,
            maxNativeZoom: 19
        });

        // Labels overlay to sit on top of satellite (makes the "Hybrid" layer)
        const labelsLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Labels &copy; Esri',
            maxZoom: 24,
            maxNativeZoom: 19,
            pane: 'overlayPane' // ensures labels render above satellite tiles
        });

        // Hybrid = satellite + labels grouped together
        const hybridLayer = L.layerGroup([satelliteLayer, labelsLayer]);

        const map = L.map(mapRef.current, {
            zoomControl: false,
            center: [20.5937, 78.9629],
            zoom: 5,
            maxZoom: 24,
            layers: [hybridLayer] // start with hybrid as default
        });
        mapInstanceRef.current = map;

        // ADD THIS SECTION
        L.control.scale({
            metric: true,
            imperial: false,
            position: 'topleft'
        }).addTo(map);


        // Layer control
        L.control.layers({ "Satellite": satelliteLayer, "Street Map": streetLayer },
            null, { position: 'topright' }).addTo(map);

        // Initialize drawn items layer
        const drawnItems = new L.FeatureGroup().addTo(map);
        drawnItemsRef.current = drawnItems;

        // Try to get user's location
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    // Safely check if map is still valid using the ref
                    if (mapInstanceRef.current && mapInstanceRef.current.getContainer()) {
                        mapInstanceRef.current.setView([position.coords.latitude, position.coords.longitude], 13);
                    }
                },
                () => console.log('Location access denied')
            );
        }

        return () => {
            if (mapInstanceRef.current) {
                mapInstanceRef.current.remove();
                mapInstanceRef.current = null;
            }
        };
    }, []);

    // Get layer type
    const getLayerType = (layer) => {
        if (layer instanceof L.Circle) return 'circle';
        if (layer instanceof L.Rectangle) return 'rectangle';
        if (layer instanceof L.Polygon) return 'polygon';
        return 'unknown';
    };

    // Update field information
    const updateFieldInfo = useCallback((layer, type) => {
        let area = 0;
        let perimeter = 0;

        if (type === 'circle') {
            const radius = layer.getRadius();
            area = Math.PI * radius * radius;
            perimeter = 2 * Math.PI * radius;
        } else if (type === 'rectangle' || type === 'polygon') {
            area = L.GeometryUtil.geodesicArea(layer.getLatLngs()[0]);
            const latlngs = layer.getLatLngs()[0];
            for (let i = 0; i < latlngs.length; i++) {
                const p1 = latlngs[i];
                const p2 = latlngs[(i + 1) % latlngs.length];
                perimeter += p1.distanceTo(p2);
            }
        }

        const hectares = (area / 10000).toFixed(2);
        const acres = (area / 4046.86).toFixed(2);

        setFieldInfo({
            area: `${hectares} ha (${acres} acres)`,
            type: type.charAt(0).toUpperCase() + type.slice(1),
            perimeter: `${(perimeter / 1000).toFixed(2)} km`
        });
    }, []);

    // Enable drawing mode
    const enableDrawing = () => {
        setShowOverlay(false);
        setShowToolbar(true);
    };

    // Start drawing
    const startDraw = (type) => {
        const map = mapInstanceRef.current;
        if (!map) return;

        if (currentLayerRef.current) {
            Swal.fire({
                text: 'Please delete the existing field before drawing a new one.',
                icon: 'warning',
                timer: 2000,
                showConfirmButton: false
            });
            return;
        }

        if (drawHandlerRef.current) {
            drawHandlerRef.current.disable();
        }

        setActiveTool(type);

        const shapeOptions = { color: '#ffffff', weight: 3, fillOpacity: 0 };

        if (type === 'polygon') {
            drawHandlerRef.current = new L.Draw.Polygon(map, {
                shapeOptions,
                allowIntersection: false,
                showArea: true
            });
        } else if (type === 'rectangle') {
            drawHandlerRef.current = new L.Draw.Rectangle(map, { shapeOptions });
        }

        drawHandlerRef.current.enable();
    };

    // Setup draw events
    useEffect(() => {
        const map = mapInstanceRef.current;
        if (!map) return;

        const handleCreated = (event) => {
            const layer = event.layer;
            const type = event.layerType;

            drawnItemsRef.current.addLayer(layer);
            currentLayerRef.current = layer;

            setActiveTool(null);
            updateFieldInfo(layer, type);
            setShowFieldInfo(true);
        };

        const handleEdited = (event) => {
            const layers = event.layers;
            layers.eachLayer((layer) => {
                updateFieldInfo(layer, getLayerType(layer));
            });
        };

        map.on(L.Draw.Event.CREATED, handleCreated);
        map.on(L.Draw.Event.EDITED, handleEdited);

        return () => {
            map.off(L.Draw.Event.CREATED, handleCreated);
            map.off(L.Draw.Event.EDITED, handleEdited);
        };
    }, [updateFieldInfo]);

    // Toggle edit mode
    const toggleEdit = () => {
        const map = mapInstanceRef.current;
        if (!map || !currentLayerRef.current) return;

        if (!editHandlerRef.current) {
            editHandlerRef.current = new L.EditToolbar.Edit(map, {
                featureGroup: drawnItemsRef.current,
                selectedPathOptions: { maintainColor: true }
            });
        }

        if (activeTool === 'edit') {
            editHandlerRef.current.disable();
            editHandlerRef.current.save();
            setActiveTool(null);
        } else {
            editHandlerRef.current.enable();
            setActiveTool('edit');
        }
    };

    // Delete layer
    const deleteLayer = () => {
        if (!currentLayerRef.current) return;

        Swal.fire({
            title: 'Delete Field?',
            text: "You won't be able to revert this!",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6',
            confirmButtonText: 'Yes, delete it!'
        }).then((result) => {
            if (result.isConfirmed) {
                drawnItemsRef.current.clearLayers();
                currentLayerRef.current = null;
                setShowFieldInfo(false);
                if (editHandlerRef.current) editHandlerRef.current.disable();
                setActiveTool(null);
            }
        });
    };

    // Save field
    const handleSave = async () => {
        if (!currentLayerRef.current) {
            Swal.fire({
                icon: 'warning',
                title: 'No Field Drawn',
                text: 'Please draw a field before saving.',
                confirmButtonColor: '#2f7a2f'
            });
            return;
        }

        const layer = currentLayerRef.current;
        const type = getLayerType(layer);
        let geometry;
        let area = 0;
        let lat, lng;

        if (type === 'circle') {
            const center = layer.getLatLng();
            lat = center.lat;
            lng = center.lng;
            const radius = layer.getRadius();
            geometry = { type: 'Circle', center: [center.lat, center.lng], radius };
            area = Math.PI * radius * radius;
        } else {
            const center = layer.getBounds().getCenter();
            lat = center.lat;
            lng = center.lng;
            geometry = layer.toGeoJSON().geometry;
            area = L.GeometryUtil.geodesicArea(layer.getLatLngs()[0]);
        }

        // On-the-fly reverse geocoding to auto-populate village, district, state
        let reverseData = { village: '', district: '', state: '' };
        Swal.fire({
            title: 'Analyzing Field Location...',
            html: 'Please wait while we determine the geographic coordinates and location details.',
            allowOutsideClick: false,
            didOpen: () => {
                Swal.showLoading();
            }
        });

        try {
            const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`);
            if (res.ok) {
                const parsed = await res.json();
                const addr = parsed.address || {};
                const rawVillage = addr.village || addr.town || addr.suburb || addr.hamlet || addr.neighbourhood || addr.city_district || addr.village_group || addr.isolated_dwellings || addr.croft || addr.municipality || addr.city || addr.township || '';
                const rawDistrict = addr.county || addr.district || addr.state_district || addr.subdistrict || '';
                const rawState = addr.state || addr.region || '';
                
                const cleanValue = (val) => {
                    if (!val || val.toLowerCase() === 'na' || /^\d+(\.\d+)?$/.test(val)) return '';
                    return val;
                };
                
                reverseData.village = cleanValue(rawVillage);
                reverseData.district = cleanValue(rawDistrict);
                reverseData.state = cleanValue(rawState);
            }
        } catch (err) {
            console.error("Reverse geocoding failed", err);
        }

        Swal.close();

        const CROP_CATEGORIES = {
            "Cereals / अनाज": ["Wheat / गेहूं", "Paddy (Rice) / धान (चावल)", "Maize / मक्का", "Barley / जौ", "Pearl Millet (Bajra) / बाजरा", "Sorghum (Jowar) / ज्वार"],
            "Pulses / दालें": ["Chickpea (Gram) / चना", "Pigeon Pea (Arhar) / अरहर", "Lentil (Masoor) / मसूर", "Black Gram (Urad) / उड़द", "Green Gram (Moong) / मूंग"],
            "Oilseeds / तिलहन": ["Mustard / सरसों", "Sesame (Til) / तिल", "Groundnut / मूंगफلی", "Linseed / अलसी"],
            "Cash Crops / नकदी फसलें": ["Sugarcane / गन्ना", "Potato / आलू", "Cotton / कपास", "Tobacco / तंबाकू"]
        };

        const { value: formValues } = await Swal.fire({
            title: '<h3 style="color:#00e676;margin-bottom:10px;font-family:\'Poppins\',sans-serif;font-weight:700;font-size:22px;">Save Field / खेत सुरक्षित करें</h3>',
            background: '#ffffff',
            customClass: {
                popup: 'premium-krishi-swal',
                confirmButton: 'krishi-confirm-btn',
                cancelButton: 'krishi-cancel-btn'
            },
            html: `
                <div class="swal-field-form" style="text-align: left; font-family: 'Poppins', sans-serif; color: #333333; max-height: 70vh; overflow-y: auto; padding-right: 6px;">
                    <div style="margin-bottom:12px;">
                        <label style="color:#333333;font-size:12px;font-weight:600;display:block;margin-bottom:4px;opacity:0.9;">Field Name / खेत का नाम <span style="color:#ff5252">*</span></label>
                        <input id="swal-field-name" class="swal2-input-custom" style="width:100%;margin:0;box-sizing:border-box;background:#f4f6f8;color:#333;border:1px solid rgba(0, 200, 83, 0.3);border-radius:8px;padding: 10px 12px;outline:none;" placeholder="e.g. North Field">
                    </div>
                    <div style="margin-bottom:12px;">
                        <label style="color:#333333;font-size:12px;font-weight:600;display:block;margin-bottom:4px;opacity:0.9;">Village / गाँव <span style="color:#ff5252">*</span></label>
                        <input id="swal-village" class="swal2-input-custom" style="width:100%;margin:0;box-sizing:border-box;background:#f4f6f8;color:#333;border:1px solid rgba(0, 200, 83, 0.3);border-radius:8px;padding: 10px 12px;outline:none;" placeholder="e.g. Rampur" value="${reverseData.village || ''}">
                    </div>
                    <div style="margin-bottom:12px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                        <div>
                            <label style="color:#333333;font-size:12px;font-weight:600;display:block;margin-bottom:4px;opacity:0.9;">District / जिला</label>
                            <input id="swal-district" class="swal2-input-custom" style="width:100%;margin:0;box-sizing:border-box;background:#f4f6f8;color:#333;border:1px solid rgba(0, 200, 83, 0.3);border-radius:8px;padding: 10px 12px;outline:none;" placeholder="e.g. Kanpur" value="${reverseData.district || ''}">
                        </div>
                        <div>
                            <label style="color:#333333;font-size:12px;font-weight:600;display:block;margin-bottom:4px;opacity:0.9;">State / राज्य</label>
                            <input id="swal-state" class="swal2-input-custom" style="width:100%;margin:0;box-sizing:border-box;background:#f4f6f8;color:#333;border:1px solid rgba(0, 200, 83, 0.3);border-radius:8px;padding: 10px 12px;outline:none;" placeholder="e.g. Uttar Pradesh" value="${reverseData.state || ''}">
                        </div>
                    </div>
                    <div style="margin-bottom:12px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                        <div>
                            <label style="color:#333333;font-size:12px;font-weight:600;display:block;margin-bottom:4px;opacity:0.9;">Crop Type / प्रकार <span style="color:#ff5252">*</span></label>
                            <select id="swal-crop-type" class="swal2-select-custom" style="width:100%;margin:0;box-sizing:border-box;background:#f4f6f8;color:#333;border:1px solid rgba(0, 200, 83, 0.3);border-radius:8px;padding: 10px 12px;height: 42px;outline:none;cursor:pointer;">
                                <option value="" style="background:#ffffff;color:#333333;">-- Select --</option>
                                ${Object.keys(CROP_CATEGORIES).map(cat => `<option value="${cat}" style="background:#ffffff;color:#333333;">${cat}</option>`).join('')}
                            </select>
                        </div>
                        <div>
                            <label style="color:#333333;font-size:12px;font-weight:600;display:block;margin-bottom:4px;opacity:0.9;">Crop Name / फसल <span style="color:#ff5252">*</span></label>
                            <select id="swal-crop-name" class="swal2-select-custom" style="width:100%;margin:0;box-sizing:border-box;background:#f4f6f8;color:#333;border:1px solid rgba(0, 200, 83, 0.3);border-radius:8px;padding: 10px 12px;height: 42px;outline:none;cursor:pointer;" disabled>
                                <option value="" style="background:#ffffff;color:#333333;">-- Select Crop --</option>
                            </select>
                        </div>
                    </div>
                    <div style="margin-bottom:12px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                        <div>
                            <label style="color:#333333;font-size:12px;font-weight:600;display:block;margin-bottom:4px;opacity:0.9;">Sowing Date / बुवाई की तिथि <span style="color:#ff5252">*</span></label>
                            <input id="swal-sowing-date" type="date" class="swal2-input-custom" style="width:100%;margin:0;box-sizing:border-box;background:#f4f6f8;color:#333;border:1px solid rgba(0, 200, 83, 0.3);border-radius:8px;padding: 9px 12px;outline:none;">
                        </div>
                        <div>
                            <label style="color:#333333;font-size:12px;font-weight:600;display:block;margin-bottom:4px;opacity:0.9;">Harvesting Date / कटाई की तिथि</label>
                            <input id="swal-harvesting-date" type="date" class="swal2-input-custom" style="width:100%;margin:0;box-sizing:border-box;background:#f4f6f8;color:#333;border:1px solid rgba(0, 200, 83, 0.3);border-radius:8px;padding: 9px 12px;outline:none;">
                        </div>
                    </div>
                </div>
            `,
            focusConfirm: false,
            showCancelButton: true,
            confirmButtonColor: '#00e676',
            cancelButtonColor: '#455a64',
            confirmButtonText: 'Save / सुरक्षित करें',
            cancelButtonText: 'Cancel / रद्द करें',
            didOpen: () => {
                const typeSelect = document.getElementById('swal-crop-type');
                const nameSelect = document.getElementById('swal-crop-name');

                typeSelect.addEventListener('change', () => {
                    const selectedType = typeSelect.value;
                    nameSelect.innerHTML = '';

                    if (!selectedType) {
                        nameSelect.disabled = true;
                        nameSelect.innerHTML = '<option value="" style="background:#ffffff;color:#333333;">-- Select Crop --</option>';
                        return;
                    }

                    nameSelect.disabled = false;
                    nameSelect.innerHTML = '<option value="" style="background:#ffffff;color:#333333;">-- Select Crop / फसल चुनें --</option>';

                    const crops = CROP_CATEGORIES[selectedType] || [];
                    crops.forEach(crop => {
                        const opt = document.createElement('option');
                        opt.value = crop;
                        opt.textContent = crop;
                        opt.style.background = '#0c1a12';
                        opt.style.color = '#fff';
                        nameSelect.appendChild(opt);
                    });

                    // Add "Other" option
                    const otherOpt = document.createElement('option');
                    otherOpt.value = 'Other';
                    otherOpt.textContent = 'Other (Specify) / अन्य (निर्दिष्ट करें)';
                    otherOpt.style.background = '#0c1a12';
                    otherOpt.style.color = '#fff';
                    nameSelect.appendChild(otherOpt);
                });

                nameSelect.addEventListener('change', async () => {
                    if (nameSelect.value === 'Other') {
                        const { value: customCrop } = await Swal.fire({
                            title: 'Enter Custom Crop Name',
                            input: 'text',
                            inputLabel: 'Custom Crop Name / कस्टम फसल का नाम',
                            inputPlaceholder: 'e.g. Mentha / पिपरमेंट',
                            showCancelButton: true,
                            confirmButtonColor: '#00e676',
                            background: '#ffffff',
                            inputValidator: (val) => {
                                if (!val) return 'Crop name cannot be empty!';
                            }
                        });

                        if (customCrop) {
                            let optExists = false;
                            for (let i = 0; i < nameSelect.options.length; i++) {
                                if (nameSelect.options[i].value === customCrop) {
                                    nameSelect.selectedIndex = i;
                                    optExists = true;
                                    break;
                                }
                            }

                            if (!optExists) {
                                const newOpt = document.createElement('option');
                                newOpt.value = customCrop;
                                newOpt.textContent = `${customCrop} (Custom / कस्टम)`;
                                newOpt.style.background = '#0c1a12';
                                newOpt.style.color = '#fff';
                                nameSelect.insertBefore(newOpt, nameSelect.lastChild);
                                nameSelect.value = customCrop;
                            }
                        } else {
                            nameSelect.value = '';
                        }
                    }
                });
            },
            preConfirm: () => {
                const name = document.getElementById('swal-field-name').value.trim();
                const village = document.getElementById('swal-village').value.trim();
                const district = document.getElementById('swal-district').value.trim();
                const state = document.getElementById('swal-state').value.trim();
                const cropType = document.getElementById('swal-crop-type').value;
                const cropName = document.getElementById('swal-crop-name').value;
                const sowingDate = document.getElementById('swal-sowing-date').value;
                const harvestingDate = document.getElementById('swal-harvesting-date').value;

                if (!name) {
                    Swal.showValidationMessage('Please enter a Field Name / कृपया खेत का नाम दर्ज करें');
                    return false;
                }
                if (!village) {
                    Swal.showValidationMessage('Please enter a Village / कृपया गाँव का नाम दर्ज करें');
                    return false;
                }
                if (!cropType) {
                    Swal.showValidationMessage('Please select a Crop Type / कृपया फसल का प्रकार चुनें');
                    return false;
                }
                if (!cropName) {
                    Swal.showValidationMessage('Please select a Crop Name / कृपया फसल का नाम चुनें');
                    return false;
                }
                if (!sowingDate) {
                    Swal.showValidationMessage('Please select a Sowing Date / कृपया बुवाई की तिथि चुनें');
                    return false;
                }

                return { name, village, district, state, cropType, cropName, sowingDate, harvestingDate };
            }
        });

        if (formValues) {
            const payload = {
                name: formValues.name,
                type,
                geometry,
                areaHectares: (area / 10000).toFixed(2),
                areaAcres: (area / 4046.86).toFixed(2),
                latitude: parseFloat(lat.toFixed(6)),
                longitude: parseFloat(lng.toFixed(6)),
                village: formValues.village,
                district: formValues.district,
                state: formValues.state,
                cropType: formValues.cropType,
                cropName: formValues.cropName,
                sowingDate: formValues.sowingDate,
                harvestingDate: formValues.harvestingDate
            };

            let backendId = null;
            let backendSaved = false;

            try {
                const result = await saveField(payload);
                if (result.success) {
                    backendId = result.id;
                    backendSaved = true;
                }
            } catch (error) {
                if (error.message && error.message.includes('Field name already exists')) {
                    Swal.fire({
                        icon: 'error',
                        title: 'Duplicate Name',
                        text: 'This field name is already taken. Please choose another.',
                        confirmButtonColor: '#d33'
                    });
                    return;
                }
                console.log('Backend save failed, using local storage');
            }

            const newField = {
                id: backendId || Date.now().toString(),
                ...payload
            };

            const fieldsLS = JSON.parse(localStorage.getItem('fields') || '[]');
            const updatedFields = [...fieldsLS, newField];
            localStorage.setItem('fields', JSON.stringify(updatedFields));

            await Swal.fire({
                icon: 'success',
                title: backendSaved ? 'Field Saved!' : 'Field Saved Locally',
                text: backendSaved
                    ? `"${formValues.name}" has been saved successfully.`
                    : `"${formValues.name}" has been saved to your browser (Backend unavailable).`,
                timer: 2000,
                confirmButtonColor: '#00c853'
            });
            navigate(`/app?field_id=${newField.id}`);
        }
    };

    // Cancel field creation
    const cancelCreation = () => {
        if (currentLayerRef.current) {
            Swal.fire({
                title: 'Discard Changes?',
                text: 'Your drawn field will be lost.',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#d33',
                cancelButtonColor: '#999',
                confirmButtonText: 'Yes, discard',
                cancelButtonText: 'Continue editing'
            }).then((result) => {
                if (result.isConfirmed) {
                    navigate('/dashboard');
                }
            });
        } else {
            navigate('/dashboard');
        }
    };

    // Initialize toolbar position
    useEffect(() => {
        if (toolbarPos.x === null && toolbarPos.y === null) {
            const defaultX = window.innerWidth / 2 - 160;
            const defaultY = window.innerHeight - 100;
            setToolbarPos({ x: defaultX, y: defaultY });
        }
    }, [toolbarPos]);

    // Toolbar drag handlers
    const handleToolbarMouseDown = (e) => {
        if (!toolbarRef.current) return;
        // Skip dragging when clicking on buttons
        if (e.target.closest('button')) return;
        setIsDraggingToolbar(true);
        const rect = toolbarRef.current.getBoundingClientRect();
        dragOffsetRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    useEffect(() => {
        const handleMouseMove = (e) => {
            if (!isDraggingToolbar) return;
            setToolbarPos({
                x: e.clientX - dragOffsetRef.current.x,
                y: e.clientY - dragOffsetRef.current.y,
            });
        };

        const handleMouseUp = () => setIsDraggingToolbar(false);

        if (isDraggingToolbar) {
            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        }

        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isDraggingToolbar]);

    // Search location
    const searchLocation = async () => {
        if (!searchQuery) return;
        setIsSearching(true);

        try {
            // Check for exact coordinates using the robust parser
            const coords = parseCoordinates(searchQuery);

            let locationData = null;

            if (coords) {
                locationData = {
                    lat: coords.lat,
                    lon: coords.lon,
                    display_name: `Exact Coordinates: ${coords.lat.toFixed(6)}, ${coords.lon.toFixed(6)}`
                };
            }

            if (!locationData) {
                // Not coordinates, call Nominatim API
                const response = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(searchQuery)}`);
                const data = await response.json();

                if (data && data.length > 0) {
                    locationData = {
                        lat: parseFloat(data[0].lat),
                        lon: parseFloat(data[0].lon),
                        display_name: data[0].display_name
                    };
                }
            }

            if (locationData) {
                const latLng = [locationData.lat, locationData.lon];

                // Clear existing marker
                if (searchMarkerRef.current) {
                    mapInstanceRef.current.removeLayer(searchMarkerRef.current);
                }

                // Add new marker
                const customIcon = L.divIcon({
                    className: 'custom-gps-marker',
                    html: `
                        <div class="marker-pin-wrapper">
                            <div class="marker-pulse"></div>
                            <div class="marker-pin">
                                <i class="fas fa-leaf"></i>
                            </div>
                        </div>
                    `,
                    iconSize: [40, 40],
                    iconAnchor: [20, 40],
                    popupAnchor: [0, -40]
                });
                const marker = L.marker(latLng, { icon: customIcon }).addTo(mapInstanceRef.current);
                marker.bindPopup(locationData.display_name).openPopup();
                searchMarkerRef.current = marker;

                // flyTo ki jagah setView use kiya. Ye bina animation ke instantly zoom karta hai (100% reliable)
                mapInstanceRef.current.flyTo(latLng, 18, {
                    duration: 3,       // 3 seconds tak animation chalega (Isse slowly feel aayega)
                    easeLinearity: 0.25 // Animation kitna "smooth" start aur end hoga
                });

                // Map ko force-refresh karne ke liye ek chhota sa delay
                // Ye ensure karega ki zoom hone ke baad map gray na ho aur tiles properly load ho jayein
                setTimeout(() => {
                    if (mapInstanceRef.current) {
                        mapInstanceRef.current.invalidateSize();
                    }
                }, 100);

            } else {
                Swal.fire({
                    icon: 'error',
                    title: 'Location not found',
                    toast: true,
                    position: 'top-end',
                    showConfirmButton: false,
                    timer: 3000
                });
            }
        } catch (error) {
            console.error('Search error:', error);
        } finally {
            setIsSearching(false);
        }
    };

    // Handle file upload
    const handleFileUpload = (event) => {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                let geojson;
                const content = e.target.result;

                if (file.name.toLowerCase().endsWith('.kml')) {
                    const parser = new DOMParser();
                    const kmlDom = parser.parseFromString(content, 'text/xml');
                    geojson = kml(kmlDom);
                } else {
                    geojson = JSON.parse(content);
                }

                if (geojson) {
                    // Start fresh
                    drawnItemsRef.current.clearLayers();
                    currentLayerRef.current = null;

                    let feature;

                    // Handle different GeoJSON structures
                    if (geojson.type === 'FeatureCollection' && geojson.features && geojson.features.length > 0) {
                        feature = geojson.features[0];
                    } else if (geojson.type === 'Feature') {
                        feature = geojson;
                    } else if (geojson.type === 'Polygon' || geojson.type === 'MultiPolygon') {
                        feature = { type: 'Feature', geometry: geojson };
                    }

                    if (feature) {
                        const layer = L.geoJSON(feature, {
                            style: { color: '#ffffff', weight: 3, fillOpacity: 0 }
                        }).getLayers()[0];

                        if (layer) {
                            drawnItemsRef.current.addLayer(layer);
                            currentLayerRef.current = layer;

                            const type = getLayerType(layer);
                            updateFieldInfo(layer, type);

                            if (layer.getBounds) {
                                mapInstanceRef.current?.fitBounds(layer.getBounds());
                            }

                            setShowOverlay(false);
                            setShowToolbar(true);
                            setShowFieldInfo(true);

                            Swal.fire({
                                icon: 'success',
                                title: 'File Uploaded',
                                text: 'Field boundary loaded successfully!',
                                timer: 1500,
                                showConfirmButton: false
                            });
                        } else {
                            throw new Error('Could not create layer from feature');
                        }
                    } else {
                        throw new Error('No valid feature found in file');
                    }
                }
            } catch (error) {
                console.error('File parse error:', error);
                Swal.fire({
                    icon: 'error',
                    title: 'Invalid File',
                    text: 'Could not parse the file. Please ensure it is valid GeoJSON or KML.'
                });
            }
        };
        reader.readAsText(file);
    };

    return (
        <div className="create-field-page">
            {/* Header */}
            <header className="create-field-header">
                <div className="header-left">
                    <Link to="/dashboard" className="brand">
                        <img src="/static/logo.png" alt="MapZest" style={{ height: 32 }} />
                    </Link>
                </div>

                <div className="search-container">
                    <input
                        type="text"
                        className="search-input"
                        placeholder="Search location..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && searchLocation()}
                    />
                    <button className="search-btn" onClick={searchLocation}>
                        <i className={`fas ${isSearching ? 'fa-spinner fa-spin' : 'fa-search'}`}></i>
                    </button>
                </div>

                <div className="header-actions">
                    <input
                        type="file"
                        id="fileInput"
                        accept=".kml,.geojson,.json"
                        style={{ display: 'none' }}
                        onChange={handleFileUpload}
                    />
                    <button className="btn btn-secondary" onClick={() => document.getElementById('fileInput').click()}>
                        <i className="fas fa-upload"></i>
                        Upload
                    </button>
                    <button className="btn btn-secondary" onClick={cancelCreation}>
                        <i className="fas fa-times"></i>
                        Exit
                    </button>
                </div>
            </header>

            {/* Map */}
            <div ref={mapRef} className="create-field-map"></div>

            {/* Start Overlay */}


            {/* Floating Toolbar */}
            {showToolbar && toolbarPos.x !== null && toolbarPos.y !== null && (
                <div
                    ref={toolbarRef}
                    className={`floating-toolbar ${isDraggingToolbar ? 'dragging' : ''}`}
                    style={{ left: toolbarPos.x, top: toolbarPos.y }}
                    onMouseDown={handleToolbarMouseDown}
                >
                    <div className="toolbar-drag-handle" title="Drag toolbar">
                        <i className="fas fa-arrows-alt"></i>
                    </div>
                    <button
                        className={`tool-btn ${activeTool === 'polygon' ? 'active' : ''}`}
                        onClick={() => startDraw('polygon')}
                        title="Draw Polygon"
                    >
                        <i className="fas fa-draw-polygon"></i>
                    </button>
                    <button
                        className={`tool-btn ${activeTool === 'rectangle' ? 'active' : ''}`}
                        onClick={() => startDraw('rectangle')}
                        title="Draw Rectangle"
                    >
                        <i className="far fa-square"></i>
                    </button>
                    <div className="divider"></div>
                    <button
                        className={`tool-btn ${activeTool === 'edit' ? 'active' : ''}`}
                        onClick={toggleEdit}
                        title="Edit Shape"
                    >
                        <i className="fas fa-pen"></i>
                    </button>
                    <button className="tool-btn save-btn" onClick={handleSave} title="Save Field">
                        <i className="fas fa-check"></i>
                    </button>
                    <button className="tool-btn delete-btn" onClick={deleteLayer} title="Delete Shape">
                        <i className="fas fa-trash"></i>
                    </button>
                </div>
            )}

            {/* Field Info Panel */}
            {showFieldInfo && (
                <div className="field-info">
                    <div className="area">{fieldInfo.area}</div>
                    <div className="meta">
                        <span>{fieldInfo.type}</span> • <span>{fieldInfo.perimeter}</span>
                    </div>
                </div>
            )}
        </div>
    );
}

export default CreateField;
