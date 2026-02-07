import asyncio
from enum import Enum, auto
from mavsdk.telemetry import FlightMode
from mavsdk import System
import math
from mavsdk.offboard import VelocityNedYaw, PositionGlobalYaw

class FlightState(Enum):
    IDLE = auto()
    ARMING = auto()
    TAKEOFF = auto()
    TRANSITION = auto()
    MISSION = auto()
    APPROACH = auto()
    LANDING = auto()
    EMERGENCY = auto()

class VtolFSM:
    def __init__(self):
        self.drone = System()
        self.state = FlightState.IDLE
        self.is_running = True
        
        print("🚁 VTOL GÖREV SİSTEMİ BAŞLATILDI")
        try:
            self.target_lat = float(input("Hedef LATITUDE: "))
            self.target_lon = float(input("Hedef LONGITUDE: "))
            self.target_alt = 50.0
            self.cruise_speed = 25.0  # 20'den 25'e çıkarıldı
            print(f"✅ Hedef: {self.target_lat}, {self.target_lon} | Hız: {self.cruise_speed} m/s")
        except ValueError:
            print("❌ HATA: Geçersiz giriş!")
            exit()

    async def run(self):
        await self.drone.connect(system_address="udp://:14540")
        print("🔗 FCU Bağlantısı bekleniyor...")
        
        async for connection_state in self.drone.core.connection_state():
            if connection_state.is_connected:
                print("✅ Bağlantı kuruldu!")
                break
        
        while self.is_running:
            if self.state == FlightState.IDLE:
                await self.handle_idle()
            elif self.state == FlightState.ARMING:
                await self.handle_arming()
            elif self.state == FlightState.TAKEOFF:
                await self.handle_takeoff()
            elif self.state == FlightState.TRANSITION:
                await self.handle_transition()
            elif self.state == FlightState.MISSION:
                await self.handle_mission()
            elif self.state == FlightState.APPROACH:
                await self.handle_approach()
            elif self.state == FlightState.LANDING:
                await self.handle_landing()
            elif self.state == FlightState.EMERGENCY:
                await self.handle_emergency()
            
            await asyncio.sleep(0.1)

    async def handle_idle(self):
        print("📡 GPS ve Sistem sağlığı kontrol ediliyor...")
        async for health in self.drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                print("✅ Sistem hazır. ARM durumuna geçiliyor.")
                self.state = FlightState.ARMING
                break
            await asyncio.sleep(1)

    async def handle_arming(self):
        print("⚡ Motorlar ARM ediliyor...")
        try:
            await self.drone.action.arm()
            self.state = FlightState.TAKEOFF
        except Exception as e:
            print(f"❌ ARM HATASI: {e}")
            self.state = FlightState.EMERGENCY

    async def handle_takeoff(self):
        print(f"⬆️ Multicopter kalkışı yapılıyor. Hedef: {self.target_alt}m")
        await self.drone.action.set_takeoff_altitude(self.target_alt)
        try:
            await self.drone.action.takeoff()
        except Exception as e:
            print(f"❌ KALKIŞ HATASI: {e}")
            self.state = FlightState.EMERGENCY
            return
        
        async for pos in self.drone.telemetry.position():
            if pos.relative_altitude_m > (self.target_alt - 2.0):
                print("✅ İrtifa alındı. Geçiş (Transition) başlıyor...")
                await asyncio.sleep(3)
                self.state = FlightState.TRANSITION
                break

    async def handle_transition(self):
        print("hedefe yöneliyor")
        
        await asyncio.sleep(5) # Geçiş öncesi stabilizasyon payı

        print("✈️ VTOL -> Sabit Kanat geçişi yapılıyor...")
        transition_speed_threshold = 15.0
        await self.drone.action.transition_to_fixedwing()
        await asyncio.sleep(2)
    
        timeout_seconds = 20
        start_time = asyncio.get_event_loop().time()

        try:
            async for pos_vel in self.drone.telemetry.position_velocity_ned():
                vn = pos_vel.velocity.north_m_s
                ve = pos_vel.velocity.east_m_s
                current_speed = math.sqrt(vn**2 + ve**2)
                elapsed_time = asyncio.get_event_loop().time() - start_time
                print(f"🚀 Mevcut Hız: {current_speed:.2f} m/s | Geçen Süre: {elapsed_time:.1f} s")

                if current_speed >= transition_speed_threshold:
                    print("✅ Güvenli hız sağlandı. Sabit kanat modunda uçuşa geçildi.")
                    self.state = FlightState.MISSION
                    break
                if elapsed_time > timeout_seconds:
                    print("⏱️ Geçiş süresi doldu. Sabit kanat moduna geçiliyor...")
                    self.state = FlightState.MISSION
                    break
                await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"❌ GEÇİŞ HATASI: {e}")
            self.state = FlightState.EMERGENCY

    def calculate_distance(self, lat1, lon1):
        """Hedefe mesafe hesapla (metre)"""
        lat_diff = (self.target_lat - lat1) * 111320
        lon_diff = (self.target_lon - lon1) * 111320 * math.cos(math.radians(lat1))
        return math.sqrt(lat_diff**2 + lon_diff**2)

    def calculate_bearing(self, lat1, lon1):
        """Hedefe bearing hesapla (derece) - DÜZELTİLDİ"""
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(self.target_lat)
        lon_diff_rad = math.radians(self.target_lon - lon1)

        y = math.sin(lon_diff_rad) * math.cos(lat2_rad)
        x = math.cos(lat1_rad) * math.sin(lat2_rad) - \
            math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(lon_diff_rad)
        # DÜZELTME: atan2(y, x) formatı - lon=y, lat=x
        bearing_rad = math.atan2(y, x)
        bearing_deg = (math.degrees(bearing_rad) + 360) % 360

        return bearing_deg

    async def handle_mission(self):
        print(f"🎯PX4 ile hedefe gidiliyor (FIXED-WING): {self.target_lat}, {self.target_lon}")
        
        await asyncio.sleep(1)
                
            
        await self.drone.action.goto_location(
          self.target_lat,
          self.target_lon,
          self.target_alt,
          float("nan")  # yaw zorlamıyoruz
       )
        print("📍 Goto komutu gönderildi, PX4 kontrolü devraldı")

        ATTACK_RADIUS = 80.0
        TOLERANCE = 50.0
        STABLE_COUNT_REQUIRED = 3
        stable_counter = 0

        async for pos in self.drone.telemetry.position():
            distance = self.calculate_distance(pos.latitude_deg, pos.longitude_deg)
            print(f"🛫 Mesafe: {distance:.1f} m")

            print(f"📍 Hedefe Mesafe: {distance:.1f} m ")
            if distance < ATTACK_RADIUS:
                stable_counter += 1
                print(f"🔄 Hedef bölgesine girdik ({stable_counter}/{STABLE_COUNT_REQUIRED})")
            else:
                stable_counter = 0

            if stable_counter >= STABLE_COUNT_REQUIRED:
                print("🎯 HEDEF BÖLGEYE VARILDI → DALIS")
                self.state = FlightState.LANDING
                break
        await asyncio.sleep(1)


    async def handle_approach(self):
        # Bu fonksiyon şu anda kullanılmıyor
        pass

    async def handle_landing(self):
        print("🎯 VTOL HIZLI İNİŞ PROSEDÜRÜ BAŞLIYOR!")
        
        try:
            # 1) Offboard'u durdur ve kontrolü FCU'ya devret
            print("⏸️ Offboard durduruluyor...")
            try:
                await self.drone.offboard.stop()
            except Exception as e:
                print(f"⚠️ Offboard durdurma uyarısı: {e}")
            
            # 2) Multicopter moduna geçiş komutu ver
            print("🔄 Multicopter moduna geçiliyor...")
            await self.drone.action.transition_to_multicopter()
            
            # --- DÜZELTİLEN KRİTİK KISIM BAŞLANGICI ---
            # 10 saniye sabit beklemek yerine, aracın modunu takip ediyoruz
            start = asyncio.get_event_loop().time()
            async for vtol in self.drone.telemetry.vtol_state():
                if str(vtol) in ["MC", "MULTICOPTER"]:
                    print("✅ Multicopter mod aktif")
                    break
                await asyncio.sleep(0.2)
                if asyncio.get_event_loop().time() - start > 8:
                    print("vtol geçişi zaman aşımına uğradı, devam ediliyor...")
                    break
                await asyncio.sleep(0.1)

            
            await self.drone.offboard.set_velocity_ned(
                VelocityNedYaw(0.0, 0.0, 0.0, float("nan"))
            )
            await self.drone.offboard.start()
            await asyncio.sleep(0.2)
           
            
            print("⬇️ HEDEFE KİLİTLİ DALIŞ BAŞLADI")

            async for pos in self.drone.telemetry.position():
                alt = pos.relative_altitude_m
                dx = (self.target_lat - pos.latitude_deg) * 111320
                dy = (self.target_lon - pos.longitude_deg) * 111320 * math.cos(
                    math.radians(pos.latitude_deg)
                )
                distance_xy = math.sqrt(dx**2 + dy**2)
                
                if distance_xy>30:
                    KP=0.06
                elif distance_xy>10:
                    KP=0.04
                else:
                    KP=0.02

                vx = KP * dx
                vy = KP * dy

                max_xy = 6.0 if alt >15 else 2.0

                vxy = math.sqrt(vx**2 + vy**2)
                if vxy > max_xy:
                    scale = max_xy / vxy
                    vx *= scale
                    vy *= scale
                vxy=math.sqrt(vx**2 + vy**2)    

                if alt > 25:
                    vz = 8.0
                elif alt > 10:
                    vz = 4.0
                else:
                    vz = 0.6
                if alt< 3.0:
                    vx=0.0
                    vy=0.0
                
                await self.drone.offboard.set_velocity_ned(
                    VelocityNedYaw(
                        north_m_s=vx,
                        east_m_s=vy,
                        down_m_s=vz,
                        yaw_deg=float("nan")
                    )
                )
                print(
                    f"🎯 XY hata: {distance_xy:.2f} m | "
                    f"Alt: {alt:.1f} m | "
                    f"Vxy: {vxy:.2f} | Vz: {vz:.1f}"
                )
                if alt < 1.0 and distance_xy < 5.0:
                    print("💥 HEDEF TAM MERKEZDEN VURULDU")
                    await self.drone.offboard.stop()
                    await self.drone.action.disarm()
                    self.is_running = False
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"❌ DALIŞ HATASI: {e}")
            await self.drone.action.land()
            self.is_running = False

    async def handle_emergency(self):
        print("🚨 ACİL DURUM: RTL!")
        try:
            await self.drone.offboard.stop()
        except:
            pass
        await self.drone.action.return_to_launch()
        self.is_running = False

if __name__ == "__main__":
    fsm = VtolFSM()
    asyncio.run(fsm.run())




  -----------kodd okey ama son dalış kısmını 100 yap ve irtifa düşmesini düzeltilmeli