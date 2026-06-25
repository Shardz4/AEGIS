use serde::{Serialize, Deserialize};
use ring_buffer::SensorEvent;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq)]
pub enum SensorType {
    GasConcentration,
    Temperature,
    Pressure,
    FlowRate,
    Vibration,
    PH,
    Level,
    Humidity,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq)]
pub enum Scenario {
    Normal,
    SlowRamp,
    FastSpike,
    Oscillating,
    FlatHigh,
}

#[derive(Debug, Clone)]
pub struct Sensor {
    pub id: u16,
    pub zone: u8,
    pub sensor_type: SensorType,
    pub current_value: f64,
    pub threshold_warning: f64,
    pub threshold_critical: f64,
    pub unit: String,
    pub noise_amplitude: f64,
    pub scenario: Scenario,
    pub baseline: f64,
    pub ticks_in_scenario: u64,
    pub seed_state: u64, // local seed state for noise
}

#[derive(Debug, Clone)]
pub struct SimConfig {
    pub num_sensors: u16,
    pub num_zones: u8,
    pub tick_rate_hz: f64,
    pub seed: u64,
}

impl Default for SimConfig {
    fn default() -> Self {
        Self {
            num_sensors: 200,
            num_zones: 8,
            tick_rate_hz: 10.0,
            seed: 42,
        }
    }
}

pub struct ScadaSimulator {
    pub sensors: Vec<Sensor>,
    pub config: SimConfig,
    pub tick_count: u64,
    pub wind_speed_m_s: f64,
    pub wind_direction_deg: f64,
    lcg: Lcg,
}

struct Lcg {
    state: u64,
}

impl Lcg {
    fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        self.state
    }

    fn next_f64(&mut self) -> f64 {
        (self.next_u64() as f64) / (u64::MAX as f64)
    }

    fn next_gaussian(&mut self) -> f64 {
        let u1 = self.next_f64().max(1e-10);
        let u2 = self.next_f64();
        (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
    }
}

impl ScadaSimulator {
    pub fn new(config: SimConfig) -> Self {
        let mut lcg = Lcg::new(config.seed);
        let mut sensors = Vec::with_capacity(config.num_sensors as usize);

        for id in 0..config.num_sensors {
            let zone = (id % config.num_zones as u16) as u8;
            
            // Cycle through sensor types
            let sensor_type = match id % 8 {
                0 => SensorType::GasConcentration,
                1 => SensorType::Temperature,
                2 => SensorType::Pressure,
                3 => SensorType::FlowRate,
                4 => SensorType::Vibration,
                5 => SensorType::PH,
                6 => SensorType::Level,
                _ => SensorType::Humidity,
            };

            let (baseline, warning, critical, unit, noise) = match sensor_type {
                SensorType::GasConcentration => (5.0, 80.0, 100.0, "ppm".to_string(), 0.5),
                SensorType::Temperature => (25.0, 85.0, 100.0, "C".to_string(), 0.3),
                SensorType::Pressure => (1.5, 8.0, 10.0, "bar".to_string(), 0.05),
                SensorType::FlowRate => (100.0, 180.0, 200.0, "m3/h".to_string(), 1.0),
                SensorType::Vibration => (2.0, 12.0, 15.0, "mm/s".to_string(), 0.1),
                SensorType::PH => (7.0, 9.5, 11.0, "pH".to_string(), 0.05),
                SensorType::Level => (50.0, 90.0, 95.0, "%".to_string(), 0.2),
                SensorType::Humidity => (45.0, 80.0, 90.0, "%".to_string(), 0.4),
            };

            sensors.push(Sensor {
                id,
                zone,
                sensor_type,
                current_value: baseline,
                threshold_warning: warning,
                threshold_critical: critical,
                unit,
                noise_amplitude: noise,
                scenario: Scenario::Normal,
                baseline,
                ticks_in_scenario: 0,
                seed_state: lcg.next_u64(),
            });
        }

        let mut sim = Self {
            sensors,
            config,
            tick_count: 0,
            wind_speed_m_s: 3.2,
            wind_direction_deg: 225.0,
            lcg,
        };

        sim.initialize_scenarios();
        sim
    }

    fn initialize_scenarios(&mut self) {
        // Randomly assign initial scenarios:
        // - 2-3 sensors to SLOW_RAMP
        // - 1 to FLAT_HIGH
        // - rest to NORMAL

        // Select 3 random indices for SLOW_RAMP (make sure they are in different zones or sensor types)
        let s1 = (self.lcg.next_u64() % self.config.num_sensors as u64) as usize;
        let mut s2 = (self.lcg.next_u64() % self.config.num_sensors as u64) as usize;
        while s2 == s1 {
            s2 = (self.lcg.next_u64() % self.config.num_sensors as u64) as usize;
        }
        let mut s3 = (self.lcg.next_u64() % self.config.num_sensors as u64) as usize;
        while s3 == s1 || s3 == s2 {
            s3 = (self.lcg.next_u64() % self.config.num_sensors as u64) as usize;
        }

        // Select 1 index for FLAT_HIGH
        let mut fh = (self.lcg.next_u64() % self.config.num_sensors as u64) as usize;
        while fh == s1 || fh == s2 || fh == s3 {
            fh = (self.lcg.next_u64() % self.config.num_sensors as u64) as usize;
        }

        self.sensors[s1].scenario = Scenario::SlowRamp;
        self.sensors[s2].scenario = Scenario::SlowRamp;
        self.sensors[s3].scenario = Scenario::SlowRamp;
        self.sensors[fh].scenario = Scenario::FlatHigh;

        // Initialize flat high baseline close to warning/critical
        let warning = self.sensors[fh].threshold_warning;
        let critical = self.sensors[fh].threshold_critical;
        self.sensors[fh].current_value = warning + (critical - warning) * 0.5; // halfway between warning and critical
    }

    pub fn inject_scenario(&mut self, zone: u8, sensor_id: u16, scenario: Scenario) {
        if let Some(sensor) = self.sensors.iter_mut().find(|s| s.id == sensor_id && s.zone == zone) {
            sensor.scenario = scenario;
            sensor.ticks_in_scenario = 0;
            if scenario == Scenario::FlatHigh {
                let warning = sensor.threshold_warning;
                let critical = sensor.threshold_critical;
                sensor.current_value = warning + (critical - warning) * 0.5;
            }
        }
    }

    pub fn tick(&mut self) -> Vec<SensorEvent> {
        self.tick_count += 1;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_micros() as u64;

        let mut events = Vec::with_capacity(self.sensors.len());

        for sensor in self.sensors.iter_mut() {
            sensor.ticks_in_scenario += 1;
            
            // Create a local noise generator using the sensor's own seed state
            let mut sensor_lcg = Lcg::new(sensor.seed_state);
            let noise = sensor_lcg.next_gaussian() * sensor.noise_amplitude;
            sensor.seed_state = sensor_lcg.next_u64(); // save back state

            match sensor.scenario {
                Scenario::Normal => {
                    // Slight drift around baseline plus noise
                    let drift = (sensor.ticks_in_scenario as f64 * 0.01).sin() * 0.1;
                    sensor.current_value = sensor.baseline + drift + noise;
                    // Clamp to make sure we don't naturally breach
                    sensor.current_value = sensor.current_value.clamp(0.0, sensor.threshold_warning - 5.0);
                }
                Scenario::SlowRamp => {
                    // Linear ramp: increase 0.5% - 1.5% of critical threshold per tick
                    let ramp_rate = sensor.threshold_critical * 0.005; // 0.5% per tick
                    let val = sensor.current_value + ramp_rate + noise;
                    // Can exceed critical
                    sensor.current_value = val.max(0.0);
                }
                Scenario::FastSpike => {
                    // Jumps rapidly: e.g. 10% of critical threshold per tick
                    let spike_rate = sensor.threshold_critical * 0.08;
                    let val = sensor.current_value + spike_rate + noise;
                    sensor.current_value = val.max(0.0);
                }
                Scenario::Oscillating => {
                    // Sine wave that occasionally crosses warning
                    let amplitude = (sensor.threshold_warning - sensor.baseline) * 1.1;
                    let period = 100.0; // ticks
                    let angle = (sensor.ticks_in_scenario as f64 / period) * 2.0 * std::f64::consts::PI;
                    sensor.current_value = sensor.baseline + amplitude * angle.sin() + noise;
                }
                Scenario::FlatHigh => {
                    // Hover at 85-95% of critical
                    let target = sensor.threshold_critical * 0.90;
                    // Slight walk around target
                    sensor.current_value = target + noise;
                }
            }

            // Map src = 0 for SCADA
            events.push(SensorEvent {
                ts: now,
                src: 0,
                zone: sensor.zone,
                signal_id: sensor.id,
                value: sensor.current_value,
                meta: vec![], // to be filled/enriched by the TTI engine later
            });
        }

        // Drifting wind parameters using the main LCG
        let wind_speed_noise = self.lcg.next_gaussian() * 0.05;
        self.wind_speed_m_s = (self.wind_speed_m_s + wind_speed_noise).clamp(0.5, 15.0);

        let wind_dir_noise = self.lcg.next_gaussian() * 1.5;
        self.wind_direction_deg = (self.wind_direction_deg + wind_dir_noise + 360.0) % 360.0;

        // Push special events for wind (zone = 255)
        // Wind Speed (ID 900)
        events.push(SensorEvent {
            ts: now,
            src: 0,
            zone: 255,
            signal_id: 900,
            value: self.wind_speed_m_s,
            meta: vec![],
        });

        // Wind Direction (ID 901)
        events.push(SensorEvent {
            ts: now,
            src: 0,
            zone: 255,
            signal_id: 901,
            value: self.wind_direction_deg,
            meta: vec![],
        });

        events
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_determinism_with_seed() {
        let config1 = SimConfig {
            num_sensors: 50,
            num_zones: 4,
            tick_rate_hz: 10.0,
            seed: 12345,
        };
        let mut sim1 = ScadaSimulator::new(config1.clone());

        let config2 = SimConfig {
            num_sensors: 50,
            num_zones: 4,
            tick_rate_hz: 10.0,
            seed: 12345,
        };
        let mut sim2 = ScadaSimulator::new(config2);

        // Verify that initial sensor states are identical
        for (s1, s2) in sim1.sensors.iter().zip(sim2.sensors.iter()) {
            assert_eq!(s1.id, s2.id);
            assert_eq!(s1.zone, s2.zone);
            assert_eq!(s1.sensor_type, s2.sensor_type);
            assert_eq!(s1.scenario, s2.scenario);
            assert_eq!(s1.current_value, s2.current_value);
        }

        // Verify that tick outputs are identical
        for _ in 0..10 {
            let events1 = sim1.tick();
            let events2 = sim2.tick();
            assert_eq!(events1.len(), events2.len());
            for (e1, e2) in events1.iter().zip(events2.iter()) {
                assert_eq!(e1.signal_id, e2.signal_id);
                assert_eq!(e1.zone, e2.zone);
                assert_eq!(e1.value, e2.value);
            }
        }
    }

    #[test]
    fn test_slow_ramp_reaches_threshold() {
        let config = SimConfig {
            num_sensors: 10,
            num_zones: 2,
            tick_rate_hz: 10.0,
            seed: 42,
        };
        let mut sim = ScadaSimulator::new(config);

        // Force a slow ramp scenario on sensor 0
        let sensor_id = sim.sensors[0].id;
        let zone = sim.sensors[0].zone;
        sim.inject_scenario(zone, sensor_id, Scenario::SlowRamp);

        let initial_val = sim.sensors[0].current_value;
        let crit_threshold = sim.sensors[0].threshold_critical;

        // Run simulation for 1200 ticks (at 0.5% increase per tick, it should definitely reach threshold)
        let mut reached = false;
        for _ in 0..1200 {
            sim.tick();
            let current_val = sim.sensors[0].current_value;
            if current_val >= crit_threshold {
                reached = true;
                break;
            }
        }

        assert!(reached, "SLOW_RAMP did not reach threshold (initial: {}, critical: {})", initial_val, crit_threshold);
    }

    #[test]
    fn test_physically_plausible_ranges() {
        let config = SimConfig::default();
        let mut sim = ScadaSimulator::new(config);

        // Run simulation for 100 ticks and verify all values stay in a reasonable range
        for _ in 0..100 {
            sim.tick();
            for sensor in &sim.sensors {
                match sensor.sensor_type {
                    SensorType::GasConcentration => {
                        assert!(sensor.current_value >= 0.0, "Gas concentration negative: {}", sensor.current_value);
                    }
                    SensorType::PH => {
                        assert!(sensor.current_value >= 0.0 && sensor.current_value <= 14.0, "pH out of range: {}", sensor.current_value);
                    }
                    SensorType::Level => {
                        assert!(sensor.current_value >= 0.0 && sensor.current_value <= 150.0, "Level out of bounds: {}", sensor.current_value);
                    }
                    SensorType::Humidity => {
                        assert!(sensor.current_value >= 0.0 && sensor.current_value <= 100.0, "Humidity out of bounds: {}", sensor.current_value);
                    }
                    _ => {
                        // General check that values aren't NaN or infinite
                        assert!(sensor.current_value.is_finite(), "Sensor value is NaN/infinite");
                    }
                }
            }
        }
    }
}

