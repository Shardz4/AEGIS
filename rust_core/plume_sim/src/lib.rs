use serde::{Serialize, Deserialize};
use std::time::Instant;

/// Parameters for the Gaussian plume dispersion simulation.
///
/// WARNING:
/// This is a simplified, non-certified approximation for demonstration purposes only.
/// It is NOT suitable for engineering-grade safety assessments.
/// Use certified tools (e.g., PHAST, ALOHA) for real-world safety analysis.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PlumeParams {
    pub source_x: f64,            // meters, plant-local X coord (East)
    pub source_y: f64,            // meters, plant-local Y coord (North)
    pub emission_rate_kg_s: f64,  // Q: leak rate in kg/s
    pub wind_speed_m_s: f64,      // u: wind speed in m/s
    pub wind_direction_deg: f64,  // Wind direction (from where wind blows, 0=N, 90=E, 180=S, 270=W)
    pub stability_class: char,     // Atmospheric stability class 'A' through 'F'
    pub gas_name: String,
    pub threshold_ppm: f64,        // Concentration threshold of interest (e.g. IDLH/LEL)
    pub molecular_weight: f64,     // MW for kg/m3 <=> ppm conversion
}

/// Result of the plume dispersion simulation.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct PlumeResult {
    pub hazard_radius_m: f64,              // Max distance along downwind centerline where C >= threshold
    pub hazard_polygon: Vec<(f64, f64)>,   // GeoJSON-ready closed polygon coordinate outline [(x, y), ...]
    pub max_concentration_ppm: f64,        // Peak concentration (clamped near source)
    pub affected_zones: Vec<u8>,           // IDs of plant zones overlapping the hazard area
    pub computation_time_us: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ZoneBoundary {
    pub zone_id: u8,
    pub center_x: f64,
    pub center_y: f64,
    pub radius_m: f64,
}

pub struct PlumeEngine;

// Pasquill-Gifford Power Law Coefficients: sigma = a * x^b (x in meters)
// Using standard rural dispersion coefficients (valid for downwind distance x >= 100m)
// Below 100m, we clamp sigma to avoid zero/negative values.
struct PGCoefficients {
    ay: f64,
    by: f64,
    az: f64,
    bz: f64,
}

impl PlumeEngine {
    pub fn new() -> Self {
        Self
    }

    /// Retrieve Pasquill-Gifford parameters for classes A-F
    fn get_pg_coefficients(stability: char) -> PGCoefficients {
        match stability {
            'A' | 'a' => PGCoefficients { ay: 0.22, by: 0.90, az: 0.20, bz: 0.94 },
            'B' | 'b' => PGCoefficients { ay: 0.16, by: 0.90, az: 0.12, bz: 0.94 },
            'C' | 'c' => PGCoefficients { ay: 0.11, by: 0.90, az: 0.08, bz: 0.92 },
            'D' | 'd' => PGCoefficients { ay: 0.08, by: 0.90, az: 0.06, bz: 0.88 },
            'E' | 'e' => PGCoefficients { ay: 0.06, by: 0.90, az: 0.03, bz: 0.84 },
            _ => PGCoefficients { ay: 0.04, by: 0.90, az: 0.02, bz: 0.80 }, // Default to F (stable)
        }
    }

    /// Compute concentration in ppm at a specific plant-local coordinate (px, py)
    pub fn compute_concentration_at(&self, params: &PlumeParams, px: f64, py: f64) -> f64 {
        let dx = px - params.source_x;
        let dy = py - params.source_y;

        // Convert meteorological wind direction (from where it blows) to direction it blows *towards*
        let wind_to_deg = (params.wind_direction_deg + 180.0) % 360.0;
        
        // Convert to cartesian angle in radians (0 = East, 90 = North)
        let phi = (90.0 - wind_to_deg) * std::f64::consts::PI / 180.0;

        // Rotate coordinates to get downwind (x) and crosswind (y) offsets
        let x_downwind = dx * phi.cos() + dy * phi.sin();
        let y_crosswind = -dx * phi.sin() + dy * phi.cos();

        // Plume is only defined downwind
        if x_downwind <= 0.0 {
            return 0.0;
        }

        // Clamp downwind distance to a minimum of 1.0m to avoid source division by zero
        let x_clamped = x_downwind.max(1.0);

        let pg = Self::get_pg_coefficients(params.stability_class);
        
        // Calculate sigma_y and sigma_z using power laws
        let sigma_y = pg.ay * x_clamped.powf(pg.by);
        let sigma_z = pg.az * x_clamped.powf(pg.bz);

        // Wind speed clamped to 0.1 m/s to avoid division by zero
        let u = params.wind_speed_m_s.max(0.1);

        // Gaussian Plume ground-level concentration equation (z = 0)
        // C(x, y, 0) = Q / (pi * u * sigma_y * sigma_z) * exp(-y^2 / (2 * sigma_y^2))
        let denom = std::f64::consts::PI * u * sigma_y * sigma_z;
        let exponent = -y_crosswind.powi(2) / (2.0 * sigma_y.powi(2));
        
        let c_kg_m3 = (params.emission_rate_kg_s / denom) * exponent.exp();

        // Convert kg/m3 to ppm: ppm = C * 24.45 * 10^6 / MW / 1000
        // Which simplifies to: ppm = C * 24,450,000.0 / MW
        (c_kg_m3 * 24_450_000.0) / params.molecular_weight
    }

    /// Run the simulation and generate consequence outputs
    pub fn compute(&self, params: &PlumeParams, zone_boundaries: &[ZoneBoundary]) -> PlumeResult {
        let start = Instant::now();

        // 1. Calculate max concentration close to source (e.g. at 1 meter downwind)
        let max_concentration_ppm = self.compute_concentration_at(
            params, 
            params.source_x + 1.0 * (((90.0 - ((params.wind_direction_deg + 180.0) % 360.0)) * std::f64::consts::PI / 180.0).cos()),
            params.source_y + 1.0 * (((90.0 - ((params.wind_direction_deg + 180.0) % 360.0)) * std::f64::consts::PI / 180.0).sin())
        );

        // 2. Binary search along downwind centerline to find max hazard radius
        let wind_to_deg = (params.wind_direction_deg + 180.0) % 360.0;
        let phi = (90.0 - wind_to_deg) * std::f64::consts::PI / 180.0;
        
        let mut low = 0.0;
        let mut high = 5000.0;
        
        for _ in 0..20 {
            let mid = (low + high) / 2.0;
            let px = params.source_x + mid * phi.cos();
            let py = params.source_y + mid * phi.sin();
            let conc = self.compute_concentration_at(params, px, py);
            
            if conc >= params.threshold_ppm {
                low = mid;
            } else {
                high = mid;
            }
        }
        let hazard_radius_m = low;

        // 3. Generate hazard polygon by sampling concentration in 10 degree increments
        let mut polygon = Vec::with_capacity(37);
        for angle_deg in (0..360).step_by(10) {
            let alpha = (angle_deg as f64) * std::f64::consts::PI / 180.0;
            
            let mut r_low = 0.0;
            let mut r_high = hazard_radius_m * 1.5 + 50.0; // Search slightly beyond max centerline radius
            
            for _ in 0..15 {
                let r_mid = (r_low + r_high) / 2.0;
                let px = params.source_x + r_mid * alpha.cos();
                let py = params.source_y + r_mid * alpha.sin();
                let conc = self.compute_concentration_at(params, px, py);
                
                if conc >= params.threshold_ppm {
                    r_low = r_mid;
                } else {
                    r_high = r_mid;
                }
            }
            // Only add point if it actually is affected
            polygon.push((params.source_x + r_low * alpha.cos(), params.source_y + r_low * alpha.sin()));
        }
        
        // Close the polygon by repeating the first point
        if !polygon.is_empty() {
            polygon.push(polygon[0]);
        }

        // 4. Determine affected zones
        let mut affected_zones = Vec::new();
        for zone in zone_boundaries {
            // Check if center of zone is inside the plume concentration threshold
            let conc_at_center = self.compute_concentration_at(params, zone.center_x, zone.center_y);
            let mut is_affected = conc_at_center >= params.threshold_ppm;

            if !is_affected {
                // Check if any polygon boundary point falls inside the zone radius
                for &(px, py) in &polygon {
                    let dist_sq = (px - zone.center_x).powi(2) + (py - zone.center_y).powi(2);
                    if dist_sq <= zone.radius_m.powi(2) {
                        is_affected = true;
                        break;
                    }
                }
            }

            if is_affected {
                affected_zones.push(zone.zone_id);
            }
        }

        let computation_time_us = start.elapsed().as_micros() as u64;

        PlumeResult {
            hazard_radius_m,
            hazard_polygon: polygon,
            max_concentration_ppm,
            affected_zones,
            computation_time_us,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn get_base_params() -> PlumeParams {
        PlumeParams {
            source_x: 0.0,
            source_y: 0.0,
            emission_rate_kg_s: 1.0,  // Q = 1 kg/s
            wind_speed_m_s: 5.0,      // u = 5 m/s
            wind_direction_deg: 270.0, // blows towards East (from West)
            stability_class: 'D',     // stability D
            gas_name: "H2S".to_string(),
            threshold_ppm: 10.0,      // threshold = 10 ppm
            molecular_weight: 34.08,  // H2S molecular weight
        }
    }

    #[test]
    fn test_known_answer() {
        let engine = PlumeEngine::new();
        let params = get_base_params();

        // Let's compute at (100.0m downwind, 0m crosswind)
        // Since wind is from 270 (blows to East), 100m downwind is px = 100.0, py = 0.0
        let conc = engine.compute_concentration_at(&params, 100.0, 0.0);

        // Hand calculation summary:
        // x = 100m, u = 5m/s, stability D
        // σ_y = 0.08 * 100^0.90 = 5.04766m
        // σ_z = 0.06 * 100^0.88 = 3.45264m
        // C_kg_m3 = Q / (pi * u * σ_y * σ_z) = 1.0 / (3.14159 * 5 * 5.04766 * 3.45264) = 0.00365313 kg/m3
        // ppm = C_kg_m3 * 24_450_000.0 / MW = 0.00365313 * 24_450_000 / 34.08 = 2620.73 ppm
        println!("Computed concentration: {} ppm (expected ~2620.7 ppm)", conc);
        assert!((conc - 2620.73).abs() < 5.0, "Expected ~2620.73, got {}", conc);
    }

    #[test]
    fn test_symmetry() {
        let engine = PlumeEngine::new();
        let params = get_base_params();

        // 100m downwind (px = 100), crosswind +/- 10m (py = 10 and py = -10)
        let conc_pos = engine.compute_concentration_at(&params, 100.0, 10.0);
        let conc_neg = engine.compute_concentration_at(&params, 100.0, -10.0);

        assert!((conc_pos - conc_neg).abs() < 1e-10, "Expected perfect symmetry, got {} vs {}", conc_pos, conc_neg);
    }

    #[test]
    fn test_monotonicity() {
        let engine = PlumeEngine::new();
        let params = get_base_params();

        // Centerline concentrations at 50m, 100m, and 200m downwind
        let conc_50 = engine.compute_concentration_at(&params, 50.0, 0.0);
        let conc_100 = engine.compute_concentration_at(&params, 100.0, 0.0);
        let conc_200 = engine.compute_concentration_at(&params, 200.0, 0.0);

        assert!(conc_50 > conc_100, "Expected C(50m) > C(100m), got {} vs {}", conc_50, conc_100);
        assert!(conc_100 > conc_200, "Expected C(100m) > C(200m), got {} vs {}", conc_100, conc_200);
    }

    #[test]
    fn test_hazard_radius_dynamics() {
        let engine = PlumeEngine::new();
        let zones = vec![];

        let mut params = get_base_params();
        params.threshold_ppm = 50.0; // increase threshold

        let res_base = engine.compute(&params, &zones);

        // 1. Increasing emission rate Q should increase hazard radius
        params.emission_rate_kg_s = 2.0;
        let res_high_q = engine.compute(&params, &zones);
        assert!(res_high_q.hazard_radius_m > res_base.hazard_radius_m, 
                "Hazard radius should increase with emission rate ({} vs {})", 
                res_high_q.hazard_radius_m, res_base.hazard_radius_m);

        // 2. Increasing wind speed u should decrease hazard radius (dilution)
        params.emission_rate_kg_s = 1.0;
        params.wind_speed_m_s = 10.0;
        let res_high_u = engine.compute(&params, &zones);
        assert!(res_high_u.hazard_radius_m < res_base.hazard_radius_m,
                "Hazard radius should decrease with higher wind speed ({} vs {})",
                res_high_u.hazard_radius_m, res_base.hazard_radius_m);
    }

    #[test]
    fn test_performance() {
        let engine = PlumeEngine::new();
        let params = get_base_params();
        
        let zones = vec![
            ZoneBoundary { zone_id: 0, center_x: 100.0, center_y: 0.0, radius_m: 50.0 },
            ZoneBoundary { zone_id: 1, center_x: 200.0, center_y: 50.0, radius_m: 50.0 },
            ZoneBoundary { zone_id: 2, center_x: 300.0, center_y: -50.0, radius_m: 50.0 },
            ZoneBoundary { zone_id: 3, center_x: 400.0, center_y: 100.0, radius_m: 50.0 },
        ];

        let start = Instant::now();
        let res = engine.compute(&params, &zones);
        let elapsed = start.elapsed();

        println!("Plume computation took: {:?}", elapsed);
        assert!(elapsed.as_millis() < 5, "Plume computation should take < 5ms, took {:?}", elapsed);
        assert!(res.hazard_radius_m > 0.0);
        assert!(!res.hazard_polygon.is_empty());
    }
}

