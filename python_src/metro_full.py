import serial
import time
import requests
import math
from google.transit import gtfs_realtime_pb2

ARDUINO_PORT = "COM7" # Portunu kontrol et
BAUD_RATE = 9600

# MTA'nın farklı hat grupları için veri bağlantıları
URLS = [
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",      # 1, 2, 3, S
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw", # N, Q, R, W
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l"     # 7 (Bazen L ile aynı sunucuda olur)
]

# Times Sq - 42 St için peron ID'leri (Güneye giden / Downtown)
STATION_IDS = {
    '1': '120S', '2': '120S', '3': '120S',
    'N': 'R16S', 'Q': 'R16S', 'R': 'R16S', 'W': 'R16S',
    '7': '725S', 'S': '902S' 
}

def get_all_arrivals():
    all_arrivals = {line: [] for line in STATION_IDS.keys()}
    current_time = int(time.time())
    
    for url in URLS:
        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            response = requests.get(url, timeout=5)
            feed.ParseFromString(response.content)
            
            for entity in feed.entity:
                if entity.HasField('trip_update'):
                    route = entity.trip_update.trip.route_id
                    if route in STATION_IDS:
                        target_stop = STATION_IDS[route]
                        for stop_update in entity.trip_update.stop_time_update:
                            if stop_update.stop_id == target_stop:
                                arr_time = stop_update.arrival.time
                                time_diff = math.floor((arr_time - current_time) / 60)
                                if time_diff >= 0:
                                    all_arrivals[route].append(time_diff)
        except Exception:
            pass # Bağlantı hatası olursa diğer URL'ye geç
            
    # Her hat için en yakın 2 treni sırala ve filtrele
    final_data = {}
    for line, times in all_arrivals.items():
        times.sort()
        if len(times) >= 2:
            final_data[line] = [times[0], times[1]]
        elif len(times) == 1:
            final_data[line] = [times[0], "-"]
        else:
            final_data[line] = ["-", "-"]
            
    return final_data

def main():
    try:
        ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1)
        print(f"{ARDUINO_PORT} acildi. Times Square Merkezi Veri Agina Baglaniliyor...")
        
        while True:
            print("\nMTA Sunucularindan Guncel Veriler Cekiliyor...")
            arrivals_data = get_all_arrivals()
            
            # Verileri çektikten sonra, hatları 5'er saniye arayla Arduino'ya gönder
            for line, times in arrivals_data.items():
                # Eğer o hatta hiç tren yoksa atla (Ekranda boşuna beklemesin)
                if times[0] == "-":
                    continue
                    
                data_packet = f"{line},{times[0]},{times[1]}\n"
                ser.write(data_packet.encode("utf-8"))
                print(f"Ekrana Verildi -> Hat: {line} | Varislari: {times[0]} dk, {times[1]} dk")
                
                time.sleep(5) # İSTENEN 5 SANİYE EKRAN SÜRESİ
                
    except KeyboardInterrupt:
        print("Kapatiliyor...")
    except Exception as e:
        print("Hata:", e)
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()