use serde::{Serialize, Deserialize};
use std::collections::{HashMap, VecDeque};

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Urgency {
    Normal = 0,
    Watch = 1,
    Warning = 2,
    Critical = 3,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct TtiResult {
    pub signal_id: u16,
    pub tti_seconds: Option<f64>,
    pub slope: f64,
    pub r_squared: f64,
    pub urgency: Urgency,
    pub current_value: f64,
    pub threshold: f64,
}

pub struct TtiEngine {
    window_size: usize,
    history: HashMap<u16, VecDeque<(u64, f64)>>, // signal_id -> VecDeque<(ts_us, value)>
}

impl TtiEngine {
    pub fn new(window_size: usize) -> Self {
        Self {
            window_size,
            history: HashMap::new(),
        }
    }

    /// Update the engine with a new reading. Returns the TtiResult.
    pub fn update(&mut self, signal_id: u16, ts_us: u64, value: f64, threshold: f64) -> TtiResult {
        let window = self.history.entry(signal_id).or_insert_with(VecDeque::new);
        
        // Add new reading
        window.push_back((ts_us, value));
        
        // Evict oldest if exceeding window size
        if window.len() > self.window_size {
            window.pop_front();
        }

        // We need at least 3 points to compute a trend and R^2 reliably
        if window.len() < 3 {
            return TtiResult {
                signal_id,
                tti_seconds: None,
                slope: 0.0,
                r_squared: 1.0,
                urgency: Urgency::Normal,
                current_value: value,
                threshold,
            };
        }

        // If current value is already at or above threshold, immediate critical TTI=0
        if value >= threshold {
            return TtiResult {
                signal_id,
                tti_seconds: Some(0.0),
                slope: 0.0,
                r_squared: 1.0,
                urgency: Urgency::Critical,
                current_value: value,
                threshold,
            };
        }

        // Linear regression: y = slope * x + intercept
        // To avoid large floating point inaccuracies and get slope in units/sec:
        // x_i = (ts_i - ts_0) in seconds
        let t0 = window[0].0;
        let mut sum_x = 0.0;
        let mut sum_y = 0.0;
        let mut sum_xy = 0.0;
        let mut sum_x2 = 0.0;
        let n = window.len() as f64;

        for (ts, val) in window.iter() {
            let x = ((*ts - t0) as f64) / 1_000_000.0; // convert microseconds to seconds
            let y = *val;
            sum_x += x;
            sum_y += y;
            sum_xy += x * y;
            sum_x2 += x * x;
        }

        let denominator = n * sum_x2 - sum_x * sum_x;
        let slope = if denominator.abs() < 1e-10 {
            0.0
        } else {
            (n * sum_xy - sum_x * sum_y) / denominator
        };
        let intercept = (sum_y - slope * sum_x) / n;

        // R^2 calculation
        let y_mean = sum_y / n;
        let mut ss_tot = 0.0;
        let mut ss_res = 0.0;

        for (ts, val) in window.iter() {
            let x = ((*ts - t0) as f64) / 1_000_000.0;
            let y = *val;
            let y_pred = slope * x + intercept;
            
            let diff_tot = y - y_mean;
            let diff_res = y - y_pred;
            
            ss_tot += diff_tot * diff_tot;
            ss_res += diff_res * diff_res;
        }

        let r_squared = if ss_tot < 1e-10 {
            if ss_res < 1e-10 { 1.0 } else { 0.0 }
        } else {
            (1.0 - (ss_res / ss_tot)).clamp(0.0, 1.0)
        };

        // TTI prediction
        let tti_seconds = if slope <= 1e-7 {
            None // flat or decreasing
        } else {
            Some((threshold - value) / slope)
        };

        // Urgency classification
        let urgency = match tti_seconds {
            Some(tti) if tti < 60.0 => Urgency::Critical,
            Some(tti) if tti < 300.0 => Urgency::Warning,
            Some(tti) if tti < 1800.0 => Urgency::Watch,
            _ => Urgency::Normal,
        };

        TtiResult {
            signal_id,
            tti_seconds,
            slope,
            r_squared,
            urgency,
            current_value: value,
            threshold,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_linear_ramp_tti() {
        let mut engine = TtiEngine::new(30);
        let threshold = 100.0;
        let mut result = None;

        // 100 ticks, value goes from 0 to 100. Let's assume each tick is 100ms (100,000 microseconds)
        // Rate of change = 1 unit per tick = 10 units / sec.
        for i in 0..=50 {
            let ts = (i * 100_000) as u64;
            let val = i as f64;
            result = Some(engine.update(1, ts, val, threshold));
        }

        let res = result.unwrap();
        // At tick 50 (value = 50.0):
        // slope should be 10.0 units/sec
        assert!((res.slope - 10.0).abs() < 1e-5);
        // R_squared should be 1.0 (perfect line)
        assert!((res.r_squared - 1.0).abs() < 1e-5);
        // remaining to threshold 100.0 is 50.0 units, so remaining time should be 50.0 / 10.0 = 5.0 seconds
        let tti = res.tti_seconds.unwrap();
        assert!((tti - 5.0).abs() < 1e-5);
        assert_eq!(res.urgency, Urgency::Critical); // 5.0 seconds is < 60 seconds (Critical)
    }

    #[test]
    fn test_flat_signal_tti() {
        let mut engine = TtiEngine::new(30);
        let threshold = 100.0;
        let mut result = None;

        for i in 0..10 {
            let ts = (i * 100_000) as u64;
            result = Some(engine.update(1, ts, 50.0, threshold));
        }

        let res = result.unwrap();
        assert!(res.tti_seconds.is_none());
        assert!(res.slope.abs() < 1e-5);
    }

    #[test]
    fn test_decreasing_signal_tti() {
        let mut engine = TtiEngine::new(30);
        let threshold = 100.0;
        let mut result = None;

        for i in 0..10 {
            let ts = (i * 100_000) as u64;
            let val = 50.0 - (i as f64);
            result = Some(engine.update(1, ts, val, threshold));
        }

        let res = result.unwrap();
        assert!(res.tti_seconds.is_none());
        assert!(res.slope < 0.0);
    }

    #[test]
    fn test_noisy_ramp_tti() {
        let mut engine = TtiEngine::new(30);
        let threshold = 100.0;
        let mut result = None;

        // Linear trend y = 2.0 * t + 10.0
        // Plus some small noise (we will use fixed pattern to avoid rand dependency in unit tests)
        let noise = [0.1, -0.2, 0.15, -0.1, 0.05, -0.15, 0.2, -0.05, 0.0, 0.1];
        
        for i in 0..30 {
            let t = (i * 100_000) as u64; // 100ms steps
            let t_sec = (i as f64) * 0.1;
            let val = 2.0 * t_sec + 10.0 + noise[i % noise.len()];
            result = Some(engine.update(1, t, val, threshold));
        }

        let res = result.unwrap();
        // Slope should be close to 2.0 units/sec
        assert!((res.slope - 2.0).abs() < 0.2);
        // R^2 should be less than 1.0 but still reasonably high
        assert!(res.r_squared < 1.0);
        assert!(res.r_squared > 0.8);
        assert!(res.tti_seconds.is_some());
    }

    #[test]
    fn test_already_breached_tti() {
        let mut engine = TtiEngine::new(30);
        let threshold = 100.0;
        
        // Push 3 normal values
        engine.update(1, 0, 80.0, threshold);
        engine.update(1, 100_000, 85.0, threshold);
        engine.update(1, 200_000, 90.0, threshold);

        // Push breached value
        let res = engine.update(1, 300_000, 105.0, threshold);
        assert_eq!(res.tti_seconds, Some(0.0));
        assert_eq!(res.urgency, Urgency::Critical);
    }
}

