document.addEventListener('DOMContentLoaded', () => {
    const API_BASE_URL = 'https://mybus-htsa.onrender.com'; 

    const routeInput = document.getElementById('route-input');
    const searchRouteBtn = document.getElementById('search-route-button');
    const routeSelect = document.getElementById('route-select');
    const busSelect = document.getElementById('bus-select');
    const getEtaButton = document.getElementById('get-eta-button');
    const etaResultsContainer = document.getElementById('eta-results-container');
    const busDetailsInfoDiv = document.getElementById('bus-details-info'); 
    const etaList = document.getElementById('eta-list');
    const loader = document.getElementById('loader');
    const messagesContainer = document.getElementById('messages-container');

    function updateSelectWithOptions(selectElement, options, defaultOptionText, disabledText) {
        selectElement.innerHTML = `<option value="">${options && options.length > 0 ? defaultOptionText : disabledText}</option>`;
        if (options && options.length > 0) {
            options.forEach(optionData => {
                const option = document.createElement('option');
                option.value = optionData.value;
                option.textContent = optionData.text;
                selectElement.appendChild(option);
            });
            selectElement.disabled = false;
        } else {
            selectElement.disabled = true;
        }
    }
    
    function showMessage(message, type = 'info') {
        messagesContainer.innerHTML = `<div class="messages ${type}">${message}</div>`;
    }

    function clearMessages() {
        messagesContainer.innerHTML = '';
    }

    function toggleLoader(show) {
        loader.style.display = show ? 'block' : 'none';
    }

    function resetBusSelect() {
        updateSelectWithOptions(busSelect, [], '-- 請先選擇路線 --', '-- 請先選擇路線 --');
        busSelect.disabled = true;
    }

    function resetEtaResults() {
        etaResultsContainer.style.display = 'none';
        busDetailsInfoDiv.innerHTML = '';
        etaList.innerHTML = '';
    }

    routeInput.addEventListener('input', () => {
        searchRouteBtn.disabled = !routeInput.value.trim();
    });

    routeInput.addEventListener('keyup', (e) => {
        if (e.key === 'Enter' && !searchRouteBtn.disabled) {
            searchRouteBtn.click();
        }
    });

    searchRouteBtn.addEventListener('click', async () => {
        clearMessages();
        const routeKeyword = routeInput.value.trim();
        if (!routeKeyword) {
            showMessage('請輸入路線關鍵字', 'info');
            return;
        }
        toggleLoader(true);
        updateSelectWithOptions(routeSelect, [],'-- 載入中... --', '-- 載入中... --');
        routeSelect.disabled = true;
        resetBusSelect();
        getEtaButton.disabled = true;
        resetEtaResults();

        try {
            const response = await fetch(`${API_BASE_URL}/api/routes?keyword=${encodeURIComponent(routeKeyword)}`);
            const data = await response.json(); 

            if (!response.ok) {
                throw new Error(data.error || `無法載入路線列表 (HTTP ${response.status})`);
            }
            if (data.error) { 
                throw new Error(data.error);
            }

            if (!data.routes || data.routes.length === 0) {
                showMessage(data.message || `找不到關鍵字 "${routeKeyword}" 的路線資訊 (TDX)。`, 'info');
                updateSelectWithOptions(routeSelect, [],'-- 無可用路線 --', '-- 無可用路線 --');
                return;
            }

            const routeOptions = data.routes.map(route => ({
                value: JSON.stringify({
                    tdx_route_name_keyword: route.tdx_route_name_keyword,
                    sub_route_uid: route.sub_route_uid,
                    route_uid: route.route_uid,
                    direction: route.direction,
                    display_name: route.display_name
                }),
                text: route.display_name
            }));
            updateSelectWithOptions(routeSelect, routeOptions, '-- 請選擇路線班次 --', '-- 無可用路線 --');

        } catch (error) {
            showMessage('載入路線時發生錯誤: ' + error.message, 'error');
            updateSelectWithOptions(routeSelect, [],'-- 載入路線失敗 --', '-- 載入路線失敗 --');
        } finally {
            toggleLoader(false);
        }
    });

    async function fetchBusesForSelectedRoute(routeParams) {
        toggleLoader(true);
        clearMessages();
        updateSelectWithOptions(busSelect, [], '-- 載入中... --', '-- 載入中... --');
        busSelect.disabled = true;
        getEtaButton.disabled = true;
        resetEtaResults();

        try {
            const queryParams = new URLSearchParams({
                direction: routeParams.direction,
                tdx_route_name_keyword: routeParams.tdx_route_name_keyword,
                route_uid: routeParams.route_uid || '',
                sub_route_uid: routeParams.sub_route_uid || '',
                display_name: routeParams.display_name
            });
            
            const response = await fetch(`${API_BASE_URL}/api/buses_for_route?${queryParams.toString()}`);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `無法載入公車列表 (HTTP ${response.status})`);
            }
            if (data.error) {
                 throw new Error(data.error);
            }
            
            if (data.no_buses_available || !data.buses || data.buses.length === 0) {
                const message = data.message || '此路線目前沒有符合條件的公車在線上。';
                showMessage(message, 'info');
                updateSelectWithOptions(busSelect, [], '-- 無可用公車 --', '-- 無可用公車 --');
                return;
            }

            const busOptions = data.buses.map(bus => ({
                value: bus.plate_numb,
                text: `${bus.plate_numb} (目前位置: ${bus.current_stop_display || '未知'})`
            }));
            updateSelectWithOptions(busSelect, busOptions, '-- 請選擇公車 --', '-- 無可用公車 --');

        } catch (error) {
            showMessage('載入公車資料時發生錯誤: ' + error.message, 'error');
            updateSelectWithOptions(busSelect, [],'-- 載入公車失敗 --', '-- 載入公車失敗 --');
        } finally {
            toggleLoader(false);
        }
    }

    routeSelect.addEventListener('change', () => {
        resetEtaResults();
        
        if (routeSelect.value) {
            try {
                const selectedRouteParams = JSON.parse(routeSelect.value);
                fetchBusesForSelectedRoute(selectedRouteParams);
            } catch (e) {
                showMessage("選擇的路線資料格式錯誤。", "error");
                resetBusSelect();
            }
        } else {
            resetBusSelect();
        }
        getEtaButton.disabled = true;
    });

    async function fetchETA(plateNumber) {
        toggleLoader(true);
        clearMessages();
        resetEtaResults();

        let routeParamsForETA;
        try {
            if (!routeSelect.value) throw new Error("請先選擇路線。");
            routeParamsForETA = JSON.parse(routeSelect.value);
        } catch (e) {
            showMessage("無法讀取所選路線資訊以查詢ETA: " + e.message, "error");
            toggleLoader(false);
            return;
        }

        const { tdx_route_name_keyword: routeNameForETA, direction: directionForETA } = routeParamsForETA;

        if (!routeNameForETA || directionForETA === undefined) {
            showMessage("路線或方向資訊不完整。", "error");
            toggleLoader(false);
            return;
        }

        try {
            const response = await fetch(`${API_BASE_URL}/api/bus_info/${plateNumber}?route_name=${encodeURIComponent(routeNameForETA)}&direction=${directionForETA}`);
            const data = await response.json();
            
            if (!response.ok) {
                 throw new Error(data.error || `無法取得預估到站時間 (HTTP ${response.status})`);
            }
            if (data.error) {
                showMessage(data.error, 'error');
                if (data.bus_details) {
                     busDetailsInfoDiv.innerHTML = `
                        <h3>公車 ${data.bus_details.plate_numb} (${data.bus_details.route_name} - ${data.bus_details.direction})</h3>
                        <p>
                            <strong>目前位置:</strong> ${data.bus_details.current_stop_name} (站序 ${data.bus_details.current_stop_sequence || 'N/A'})<br>
                            <strong>GPS時間:</strong> ${data.bus_details.gps_time || 'N/A'}
                        </p>`;
                }
                etaResultsContainer.style.display = 'block';
                return; 
            }
            
            if (data.bus_details) {
                busDetailsInfoDiv.innerHTML = `
                    <h3>公車 ${data.bus_details.plate_numb} (${data.bus_details.route_name} - ${data.bus_details.direction})</h3>
                    <p>
                        <strong>目前位置:</strong> ${data.bus_details.current_stop_name} (站序 ${data.bus_details.current_stop_sequence || 'N/A'})<br>
                        <strong>GPS時間:</strong> ${data.bus_details.gps_time || 'N/A'}
                    </p>
                `;
            }

            if (data.upcoming_stops && data.upcoming_stops.length > 0) {
                data.upcoming_stops.forEach(stop => {
                    const li = document.createElement('li');
                    li.textContent = `停靠站 ${stop.stop_sequence}: ${stop.stop_name} - ${stop.arrival_status}`;
                    etaList.appendChild(li);
                });
            } else if (data.message) {
                const messageItem = document.createElement('li');
                messageItem.textContent = data.message;
                etaList.appendChild(messageItem);
            } else { 
                const noStopsItem = document.createElement('li');
                noStopsItem.textContent = "目前無此公車後續停靠站的預估時間。";
                etaList.appendChild(noStopsItem);
            }
            etaResultsContainer.style.display = 'block';

        } catch (error) {
            showMessage(`無法取得預估到站時間: ${error.message}`, 'error');
        } finally {
            toggleLoader(false);
        }
    }

    busSelect.addEventListener('change', () => {
        getEtaButton.disabled = !(routeSelect.value && busSelect.value);
        resetEtaResults();
    });

    getEtaButton.addEventListener('click', () => {
        if (busSelect.value) {
            fetchETA(busSelect.value);
        }
    });
});