from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
from auth_TDX import get_tdx_access_token, fetch_tdx_data_with_token, app_id as tdx_app_id, app_key as tdx_app_key

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(__name__, static_folder=STATIC_DIR)


CORS(app, origins=[
    "https://myybuss.netlify.app",
    "https://heronsky.github.io",
])


TDX_API_BASE_URL = "https://tdx.transportdata.tw/api/basic"


def get_bus_stop_info_logic(target_plate, route_name_param=None, direction_param=None):
    results = {
        "bus_details": None,
        "upcoming_stops": [],
        "message": None,
        "error": None
    }
    access_token = get_tdx_access_token()
    if not access_token:
        results["error"] = "無法獲取 TDX 存取權杖。"
        return results

    current_bus_info_tdx = None
    if route_name_param and target_plate:
        api_url_realtime = f"{TDX_API_BASE_URL}/v2/Bus/RealTimeNearStop/Streaming/InterCity/{route_name_param}"
        params_realtime = {'$filter': f"PlateNumb eq '{target_plate}'", '$format': 'JSON'}
        realtime_data_list, error_rt = fetch_tdx_data_with_token(api_url_realtime, access_token, params=params_realtime)

        if error_rt is not None:
            results["error"] = f"TDX API 錯誤 (代碼: {error_rt}) (查詢公車即時資訊時)。"
            if error_rt == 429: results["error"] = "TDX API 請求過於頻繁 (查詢公車即時資訊時)。"
            return results
        
        if isinstance(realtime_data_list, list):
            for bus_rt_data in realtime_data_list:
                if direction_param is None or bus_rt_data.get('Direction') == direction_param:
                    current_bus_info_tdx = bus_rt_data
                    break 
            if not current_bus_info_tdx and realtime_data_list:
                 current_bus_info_tdx = realtime_data_list[0]

    if not current_bus_info_tdx:
        results["error"] = f"TDX 資料中找不到車牌為 {target_plate} 的公車即時資訊。"
        return results

    bus_plate_numb = current_bus_info_tdx.get('PlateNumb')
    bus_route_name_from_tdx = current_bus_info_tdx.get('RouteName', {}).get('Zh_tw', route_name_param or 'N/A')
    bus_sub_route_name_from_tdx = current_bus_info_tdx.get('SubRouteName', {}).get('Zh_tw', bus_route_name_from_tdx)
    bus_direction = current_bus_info_tdx.get('Direction')
    bus_route_uid = current_bus_info_tdx.get('RouteUID')
    bus_sub_route_uid = current_bus_info_tdx.get('SubRouteUID')

    if direction_param is not None and bus_direction != direction_param:
        app.logger.warning(f"Bus {target_plate} reported direction {bus_direction} differs from requested {direction_param}. Proceeding with bus's reported direction.")

    results["bus_details"] = {
        "plate_numb": bus_plate_numb,
        "route_name": bus_sub_route_name_from_tdx,
        "direction": '返程' if bus_direction == 1 else '去程' if bus_direction == 0 else 'N/A',
        "current_stop_name": current_bus_info_tdx.get('StopName', {}).get('Zh_tw', '未知'),
        "current_stop_sequence": current_bus_info_tdx.get('StopSequence', 'N/A'),
        "gps_time": current_bus_info_tdx.get('GPSTime')
    }
    
    api_url_stops = f"{TDX_API_BASE_URL}/v2/Bus/StopOfRoute/InterCity/{route_name_param}" 
    stops_of_route_data_full, error_stops = fetch_tdx_data_with_token(api_url_stops, access_token, params={'$format': 'JSON'})

    if error_stops is not None:
        results["error"] = f"TDX API 錯誤 (代碼: {error_stops}) (查詢站序資料時)。"
        if error_stops == 429: results["error"] = "TDX API 請求過於頻繁 (查詢站序資料時)。"
        return results

    route_specific_stops_data = None
    selected_variant_route_uid_for_s2s = None
    selected_variant_sub_route_uid_for_s2s = None

    if stops_of_route_data_full and isinstance(stops_of_route_data_full, list):
        if bus_sub_route_uid and bus_sub_route_uid != bus_route_uid:
            for route_variant in stops_of_route_data_full:
                if route_variant.get('SubRouteUID') == bus_sub_route_uid and route_variant.get('Direction') == bus_direction:
                    route_specific_stops_data = route_variant.get('Stops', [])
                    selected_variant_route_uid_for_s2s = route_variant.get('RouteUID')
                    selected_variant_sub_route_uid_for_s2s = route_variant.get('SubRouteUID')
                    break
        
        if not route_specific_stops_data:
            for route_variant in stops_of_route_data_full:
                if route_variant.get('RouteUID') == bus_route_uid and route_variant.get('Direction') == bus_direction:
                    tdx_variant_sub_route_name = route_variant.get('SubRouteName',{}).get('Zh_tw')
                    if bus_sub_route_uid == bus_route_uid and tdx_variant_sub_route_name and bus_sub_route_name_from_tdx != tdx_variant_sub_route_name:
                        continue

                    route_specific_stops_data = route_variant.get('Stops', [])
                    selected_variant_route_uid_for_s2s = route_variant.get('RouteUID')
                    selected_variant_sub_route_uid_for_s2s = route_variant.get('SubRouteUID')
                    break

        if not route_specific_stops_data:
            for route_variant in stops_of_route_data_full:
                if route_variant.get('Direction') == bus_direction:
                    route_specific_stops_data = route_variant.get('Stops', [])
                    selected_variant_route_uid_for_s2s = route_variant.get('RouteUID')
                    selected_variant_sub_route_uid_for_s2s = route_variant.get('SubRouteUID')
                    break
    
    if not route_specific_stops_data:
        results["error"] = f"無法從 TDX 獲取路線 {bus_sub_route_name_from_tdx} (UID: {bus_route_uid}/{bus_sub_route_uid}) 方向 {bus_direction} 的精確站序資料。"
        return results

    api_url_eta = f"{TDX_API_BASE_URL}/v2/Bus/EstimatedTimeOfArrival/Streaming/InterCity/{bus_route_name_from_tdx}"
    params_eta = {'$filter': f"PlateNumb eq '{target_plate}' and Direction eq {bus_direction}", '$format': 'JSON'}
    eta_data_list_for_bus, error_eta = fetch_tdx_data_with_token(api_url_eta, access_token, params=params_eta)

    if error_eta is not None:
        if error_eta == 429 : results["message"] = ((results.get("message") or "") + " 注意: 預估到站API請求頻繁; ").strip()
        eta_data_list_for_bus = None

    if eta_data_list_for_bus and not isinstance(eta_data_list_for_bus, list):
        eta_data_list_for_bus = None

    s2s_data_for_route_direction = None
    api_url_s2s = f"{TDX_API_BASE_URL}/v2/Bus/S2STravelTime/InterCity/{route_name_param}" 
    s2s_data_list_full, error_s2s = fetch_tdx_data_with_token(api_url_s2s, access_token, params={'$format': 'JSON'})

    if error_s2s is not None:
        message_addon = ""
        if error_s2s == 429: message_addon = " 注意: S2S資料API請求頻繁; "
        results["message"] = ((results.get("message") or "") + message_addon).strip()
        s2s_data_list_full = None
    
    if isinstance(s2s_data_list_full, list):
        for s2s_entry in s2s_data_list_full:
            s2s_matches_route_uid = s2s_entry.get('RouteUID') == selected_variant_route_uid_for_s2s
            s2s_matches_sub_route_uid = s2s_entry.get('SubRouteUID') == selected_variant_sub_route_uid_for_s2s
            s2s_matches_direction = s2s_entry.get('Direction') == bus_direction

            if selected_variant_sub_route_uid_for_s2s and \
               selected_variant_sub_route_uid_for_s2s != selected_variant_route_uid_for_s2s and \
               s2s_matches_sub_route_uid and s2s_matches_direction:
                s2s_data_for_route_direction = s2s_entry
                break
            elif s2s_matches_route_uid and s2s_matches_sub_route_uid and s2s_matches_direction:
                s2s_data_for_route_direction = s2s_entry
                break
        
        if not s2s_data_for_route_direction and s2s_data_list_full:
            pass

    actual_current_stop_sequence = -1
    if results["bus_details"]["current_stop_name"] != '未知':
        for idx, stop_obj in enumerate(route_specific_stops_data):
            if stop_obj.get('StopName',{}).get('Zh_tw') == results["bus_details"]["current_stop_name"]:
                actual_current_stop_sequence = stop_obj.get('StopSequence', idx)
                results["bus_details"]["current_stop_sequence"] = actual_current_stop_sequence
                break
    
    if actual_current_stop_sequence == -1 and isinstance(results["bus_details"]["current_stop_sequence"], str) :
         pass


    stops_found = False
    current_bus_time = None
    if results["bus_details"]["gps_time"]:
        try:
            current_bus_time = datetime.strptime(results["bus_details"]["gps_time"], "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            pass

    for stop_in_route in route_specific_stops_data:
        stop_sequence_tdx = stop_in_route.get('StopSequence')
        if isinstance(actual_current_stop_sequence, int) and actual_current_stop_sequence != -1 and \
           stop_sequence_tdx <= actual_current_stop_sequence:
            continue
        stops_found = True

        stop_id_tdx = stop_in_route.get('StopID')
        stop_name_tdx = stop_in_route.get('StopName', {}).get('Zh_tw', '未知站名')
        status = "未知 (TDX)"

        stop_eta_found_in_list = False 
        if eta_data_list_for_bus and isinstance(eta_data_list_for_bus, list):
            for eta_entry in eta_data_list_for_bus:
                if eta_entry.get('StopID') == stop_id_tdx:
                    stop_eta_found_in_list = True
                    estimate_time_seconds = eta_entry.get('EstimateTime')
                    if estimate_time_seconds is not None:
                        if estimate_time_seconds < 0:
                            if estimate_time_seconds == -1: status = "尚未發車 (TDX)"
                            elif estimate_time_seconds == -2: status = "交管不停靠 (TDX)"
                            elif estimate_time_seconds == -3: status = "末班車已過 (TDX)"
                            elif estimate_time_seconds == -4: status = "今日未營運 (TDX)"
                            else: status = f"狀態 {estimate_time_seconds} (TDX)"
                        else:
                            data_time_str = eta_entry.get('DataTime')
                            if data_time_str:
                                try:
                                    base_dt = datetime.strptime(data_time_str, "%Y-%m-%dT%H:%M:%S%z")
                                    arrival_dt = base_dt + timedelta(seconds=estimate_time_seconds)
                                    status = arrival_dt.strftime("%H:%M:%S") + " (TDX API)"
                                except ValueError:
                                    status = f"{estimate_time_seconds // 60}分{estimate_time_seconds % 60}秒 (TDX Raw)"
                            else:
                                status = f"{estimate_time_seconds // 60}分{estimate_time_seconds % 60}秒 (TDX Raw)"
                    elif eta_entry.get('NextBusTime'):
                        try:
                            next_bus_dt = datetime.strptime(eta_entry.get('NextBusTime'), "%Y-%m-%dT%H:%M:%S%z")
                            status = next_bus_dt.strftime("%H:%M:%S") + " (TDX NextBusTime)"
                        except (ValueError, TypeError):
                            status = "時間格式錯誤 (TDX NextBusTime)"
                    else:
                        status = "API未提供預估秒數 (TDX)"
                    break
        
        if not stop_eta_found_in_list and eta_data_list_for_bus:
            pass

        if status in ["未知 (TDX)", "API未提供預估秒數 (TDX)"]:
            if s2s_data_list_full is None:
                status = "無法預估 (S2S API失敗)"
            elif not s2s_data_for_route_direction:
                status = "無法預估 (S2S無適用路線資料)"
            elif not current_bus_time:
                status = "無法預估 (缺公車GPS時間)"
            elif not (isinstance(actual_current_stop_sequence, int) and actual_current_stop_sequence != -1):
                status = "無法預估 (未知目前站序)"
            else:
                s2s_applicable_times_collection = None

                if s2s_data_for_route_direction.get('TravelTimes') and isinstance(s2s_data_for_route_direction['TravelTimes'], list):
                    bus_weekday = current_bus_time.weekday()
                    bus_hour = current_bus_time.hour

                    for time_segment in s2s_data_for_route_direction['TravelTimes']:
                        segment_weekday = time_segment.get('Weekday')
                        segment_start_hour = time_segment.get('StartHour')
                        segment_end_hour = time_segment.get('EndHour')

                        if (segment_weekday is not None and
                            segment_start_hour is not None and
                            segment_end_hour is not None and
                            segment_weekday == bus_weekday and
                            segment_start_hour <= bus_hour < segment_end_hour):
                            s2s_applicable_times_collection = time_segment.get('S2STimes')
                            break
                
                if not isinstance(s2s_applicable_times_collection, list):
                    if not s2s_data_for_route_direction.get('TravelTimes'):
                        status = "無法預估 (S2S資料缺失TravelTimes)"
                    elif s2s_data_for_route_direction.get('TravelTimes') and not s2s_applicable_times_collection:
                         status = "無法預估 (S2S無適用時段)"
                else :
                    calculation_possible = True
                    cumulative_s2s_time = 0 
                    for i in range(actual_current_stop_sequence, stop_sequence_tdx):
                        from_stop_obj_s2s = next((s for s in route_specific_stops_data if s.get('StopSequence') == i), None)
                        to_stop_obj_s2s = next((s for s in route_specific_stops_data if s.get('StopSequence') == i + 1), None)

                        if not from_stop_obj_s2s or not to_stop_obj_s2s:
                            calculation_possible = False
                            break
                        
                        from_stop_id_calc_s2s = from_stop_obj_s2s.get('StopID')
                        to_stop_id_calc_s2s = to_stop_obj_s2s.get('StopID')

                        segment_time_info_s2s = next((
                            t for t in s2s_applicable_times_collection
                            if t.get('FromStopID') == from_stop_id_calc_s2s and t.get('ToStopID') == to_stop_id_calc_s2s
                        ), None)
                        
                        if segment_time_info_s2s and segment_time_info_s2s.get('RunTime', -1) >= 0:
                            cumulative_s2s_time += segment_time_info_s2s.get('RunTime')
                        else:
                            calculation_possible = False
                            break
                
                if calculation_possible:
                    estimated_time_s2s = current_bus_time + timedelta(seconds=cumulative_s2s_time)
                    status = estimated_time_s2s.strftime("%H:%M:%S") + " (S2S計算)"
                elif not calculation_possible:
                    status = "無法預估 (S2S計算時缺資料)"
        
        results["upcoming_stops"].append({
            "stop_sequence": stop_sequence_tdx,
            "stop_name": stop_name_tdx,
            "arrival_status": status
        })

    if not stops_found and actual_current_stop_sequence != -1 :
        results["message"] = "此車輛可能已過最後一站，或無後續停靠站資料 (TDX)。"
    elif actual_current_stop_sequence == -1:
        results["message"] = "無法確定公車目前位置序列，可能影響預估 (TDX)。"
            
    return results


def fetch_available_routes_logic(route_keyword):
    access_token = get_tdx_access_token()
    if not access_token:
        return {"error": "無法獲取 TDX 存取權杖。", "routes": []}

    api_url = f"{TDX_API_BASE_URL}/v2/Bus/StopOfRoute/InterCity/{route_keyword}"
    params = {'$format': 'JSON'}
    
    tdx_route_data, error_code = fetch_tdx_data_with_token(api_url, access_token, params=params)

    if error_code is not None:
        error_msg = f"TDX API 錯誤 (代碼: {error_code})，無法獲取 '{route_keyword}' 路線資料。"
        if error_code == 429:
            error_msg = f"TDX API 請求過於頻繁，無法獲取 '{route_keyword}' 路線資料。"
        return {"error": error_msg, "routes": []}

    if not tdx_route_data:
        return {"error": f"TDX API 未回傳 '{route_keyword}' 的路線資料，或路線不存在。", "routes": []}
    
    available_routes_info = []
    seen_display_names = set()

    if isinstance(tdx_route_data, list):
        sorted_tdx_route_data = sorted(
            tdx_route_data, 
            key=lambda rv: (
                rv.get('RouteUID', ''), 
                rv.get('SubRouteUID', ''), 
                rv.get('Direction', -1)
            )
        )

        for route_variant in sorted_tdx_route_data:
            route_name_obj = route_variant.get('RouteName', {})
            sub_route_name_obj = route_variant.get('SubRouteName', route_name_obj) 

            display_name_str = sub_route_name_obj.get('Zh_tw')
            if not display_name_str:
                display_name_str = route_name_obj.get('Zh_tw', '未知路線')
            
            direction = route_variant.get('Direction')
            direction_str = '返程' if direction == 1 else '去程' if direction == 0 else '未知方向'
            
            final_display_name = f"{display_name_str} ({direction_str})"

            if final_display_name in seen_display_names:
                continue
            seen_display_names.add(final_display_name)
            
            route_entry = {
                "display_name": final_display_name,
                "tdx_route_name_keyword": route_keyword, 
                "sub_route_uid": route_variant.get('SubRouteUID'),
                "route_uid": route_variant.get('RouteUID'),
                "direction": direction,
                "original_name_for_matching": display_name_str 
            }
            available_routes_info.append(route_entry)
            
    if not available_routes_info:
        return {"message": f"TDX 資料中找不到路線 '{route_keyword}' 的班次資訊。", "routes": []}
    return {"routes": available_routes_info}


def fetch_buses_for_route_logic(selected_route_params):
    access_token = get_tdx_access_token()
    if not access_token:
        return {"error": "無法獲取 TDX 存取權杖。", "buses": []}

    route_name = selected_route_params.get("tdx_route_name_keyword") 
    direction = selected_route_params.get("direction")
    route_uid_filter = selected_route_params.get("route_uid")
    sub_route_uid_filter = selected_route_params.get("sub_route_uid")

    if not route_name:
        return {"error": "缺少 TDX 路線名稱關鍵字。", "buses": []}
    if direction is None: 
        return {"error": "缺少路線方向。", "buses": []}

    api_url = f"{TDX_API_BASE_URL}/v2/Bus/RealTimeNearStop/Streaming/InterCity/{route_name}"
    params = {'$format': 'JSON'}
    filter_parts = []
    if sub_route_uid_filter and sub_route_uid_filter != route_uid_filter:
        filter_parts.append(f"SubRouteUID eq '{sub_route_uid_filter}'")
    elif route_uid_filter:
        filter_parts.append(f"RouteUID eq '{route_uid_filter}'")
    filter_parts.append(f"Direction eq {direction}")
    params['$filter'] = " and ".join(filter_parts)
    
    tdx_bus_data_raw, error_code = fetch_tdx_data_with_token(api_url, access_token, params=params)

    if error_code is not None:
        error_msg = f"TDX API 錯誤 (代碼: {error_code})，無法獲取公車資料。"
        if error_code == 429:
            error_msg = "TDX API 請求過於頻繁，請稍後再試。"
        return {"error": error_msg, "buses": []}
    
    filtered_buses_py = []
    if isinstance(tdx_bus_data_raw, list):
        for bus in tdx_bus_data_raw:
            if not isinstance(bus, dict): continue
            
            bus_plate = bus.get("PlateNumb")
            if not bus_plate or bus_plate == "-1": continue

            bus_status = bus.get('BusStatus')
            if bus_status in [3, 4]: 
                continue

            bus_matches_direction = bus.get('Direction') == direction
            bus_matches_route_uid_type = False

            current_bus_sub_route_uid = bus.get('SubRouteUID')
            current_bus_route_uid = bus.get('RouteUID')

            if sub_route_uid_filter and sub_route_uid_filter != route_uid_filter:
                if current_bus_sub_route_uid == sub_route_uid_filter:
                    bus_matches_route_uid_type = True
            elif route_uid_filter:
                if current_bus_route_uid == route_uid_filter:
                    if not current_bus_sub_route_uid or \
                       current_bus_sub_route_uid == route_uid_filter or \
                       current_bus_sub_route_uid == sub_route_uid_filter:
                        bus_matches_route_uid_type = True
            else:
                bus_matches_route_uid_type = True 

            if bus_matches_direction and bus_matches_route_uid_type:
                filtered_buses_py.append(bus)

    if not filtered_buses_py:
        return {"message": f"路線 '{selected_route_params.get('display_name', route_name)}' (Filter: {params.get('$filter')}) 目前沒有符合條件的公車在線上 (TDX)。", "buses": [], "no_buses_available": True}

    buses_on_selected_route = []
    for bus_data in filtered_buses_py:
        buses_on_selected_route.append({
            "plate_numb": bus_data.get("PlateNumb"),
            "current_stop_display": bus_data.get('StopName', {}).get('Zh_tw', '未知位置'),
            "sub_route_uid": bus_data.get("SubRouteUID"), 
            "route_uid": bus_data.get("RouteUID"),
            "direction": bus_data.get("Direction")
        })
    
    if not buses_on_selected_route: 
        return {"message": f"路線 '{selected_route_params.get('display_name', route_name)}' (Python Filtered) 目前沒有偵測到任何公車在線上 (TDX)。", "buses": [], "no_buses_available": True}
    return {"buses": buses_on_selected_route}


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/routes', methods=['GET'])
def api_get_routes():
    route_keyword = request.args.get('keyword')
    if not route_keyword:
        return jsonify({"error": "缺少 'keyword' (路線關鍵字) 參數"}), 400
    return jsonify(fetch_available_routes_logic(route_keyword))

@app.route('/api/buses_for_route', methods=['GET'])
def api_get_buses_for_route():
    try:
        direction_str = request.args.get('direction')
        if direction_str is None:
            return jsonify({"error": "缺少 'direction' 參數"}), 400
        direction = int(direction_str)

        tdx_route_name_keyword = request.args.get('tdx_route_name_keyword')
        route_uid = request.args.get('route_uid') 
        sub_route_uid = request.args.get('sub_route_uid')
        display_name = request.args.get('display_name')

        if not tdx_route_name_keyword:
            return jsonify({"error": "缺少 'tdx_route_name_keyword' 參數"}), 400
        
        selected_route_params = {
            "tdx_route_name_keyword": tdx_route_name_keyword,
            "route_uid": route_uid, 
            "sub_route_uid": sub_route_uid,
            "direction": direction,
            "display_name": display_name 
        }
        
        return jsonify(fetch_buses_for_route_logic(selected_route_params))
    except ValueError:
        return jsonify({"error": "'direction' 參數必須是整數。"}), 400
    except Exception as e:
        app.logger.error(f"/api/buses_for_route 發生錯誤: {e}", exc_info=True)
        return jsonify({"error": "伺服器內部錯誤"}), 500

@app.route('/api/bus_info/<plate_numb>', methods=['GET'])
def api_get_bus_info(plate_numb):
    if not plate_numb:
        return jsonify({"error": "車牌號碼不可為空。"}), 400
    
    route_name = request.args.get('route_name')
    direction_str = request.args.get('direction')
    
    if not route_name:
        return jsonify({"error": "缺少 'route_name' 參數以查詢公車資訊。"}), 400
    if direction_str is None:
        return jsonify({"error": "缺少 'direction' 參數以查詢公車資訊。"}), 400
    
    try:
        direction = int(direction_str)
    except ValueError:
        return jsonify({"error": "'direction' 參數必須是整數。"}), 400
        
    return jsonify(get_bus_stop_info_logic(plate_numb, route_name_param=route_name, direction_param=direction))

if __name__ == '__main__':
    static_index_html_path = os.path.join(STATIC_DIR, 'index.html')
    if not os.path.isdir(STATIC_DIR):
        print(f"嚴重錯誤: 'static' 資料夾不存在。")
        exit(1)
    elif not os.path.exists(static_index_html_path):
        print(f"提示: 'static/index.html' 檔案不存在。")
        
    print(f"資訊: 系統設定為從 TDX API 獲取公車資料。請確保 TDX_APP_ID 和 TDX_APP_KEY 環境變數已設定。")
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get("PORT", 5001)))