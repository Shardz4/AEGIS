/**
 * Voice Announcer Module using Web Speech API
 *
 * Provides control room spoken announcements when alerts are triggered.
 */

const ZONE_NAMES = [
    'Tank Farm', 'Compressor Hall', 'Reactor Area', 'Pipe Rack',
    'Control Room', 'Loading Bay', 'Utilities', 'Flare Stack'
];
const ZONE_IDS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

export class VoiceAnnouncer {
    constructor(buttonEl) {
        this.button = buttonEl;
        this.enabled = localStorage.getItem('aegis_voice_enabled') === 'true';
        this.synth = window.speechSynthesis;
        this.currentUtterance = null;
        
        // Set initial button state
        this.updateButtonUI();
        
        // Bind click listener
        this.button.addEventListener('click', () => this.toggle());
    }
    
    toggle() {
        this.enabled = !this.enabled;
        localStorage.setItem('aegis_voice_enabled', String(this.enabled));
        this.updateButtonUI();
        
        if (!this.enabled && this.synth) {
            // Cancel active speech immediately
            this.synth.cancel();
        }
    }
    
    updateButtonUI() {
        if (this.enabled) {
            this.button.textContent = 'VOICE ON';
            this.button.classList.add('active');
        } else {
            this.button.textContent = 'VOICE OFF';
            this.button.classList.remove('active');
        }
    }
    
    announce(alertData) {
        if (!this.enabled || !this.synth) return;
        
        // Cancel current speaking if any
        this.synth.cancel();
        
        const zoneId = alertData.zone_id;
        const zoneLetter = ZONE_IDS[zoneId] || String(zoneId);
        const zoneName = ZONE_NAMES[zoneId] || '';
        const riskScore = Math.round(alertData.risk_score);
        const urgency = alertData.urgency || 'warning';
        
        // Construct announcement text
        let text = `Alert. Zone ${zoneLetter}, ${zoneName}, has ${urgency} safety risk. Risk score is ${riskScore} percent. `;
        
        if (alertData.actions && alertData.actions.length > 0) {
            text += `Priority recommended action: ${alertData.actions[0]}`;
        }
        
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.95; // Slightly slower for clarity
        utterance.pitch = 1.0;
        
        // Select default English voice if available
        const voices = this.synth.getVoices();
        const englishVoice = voices.find(v => v.lang.startsWith('en-'));
        if (englishVoice) {
            utterance.voice = englishVoice;
        }
        
        this.currentUtterance = utterance;
        this.synth.speak(utterance);
    }
}
