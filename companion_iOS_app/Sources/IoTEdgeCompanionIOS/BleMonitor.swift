import Combine
import CoreBluetooth
import Foundation

final class BleMonitor: NSObject, ObservableObject, CBCentralManagerDelegate {
    @Published private(set) var isMonitoring = false
    @Published private(set) var isScanning = false
    @Published private(set) var bluetoothState = "Non inizializzato"
    @Published private(set) var statusMessage = "Monitoraggio BLE fermo"
    @Published private(set) var lastObservation: BeaconObservation?
    @Published private(set) var recentObservations: [BeaconObservation] = []

    private var centralManager: CBCentralManager!
    private var settings: EdgeSettings?
    private var mapping = BeaconMapping.parse("")
    private var discoveredObservations: [String: BeaconObservation] = [:]
    private var observations: [String: BeaconObservation] = [:]
    private var scanTimer: Timer?
    private var nextScanTimer: Timer?

    private let scanDurationSeconds: TimeInterval = 5
    private let pauseBetweenScansSeconds: TimeInterval = 10

    override init() {
        super.init()
        centralManager = CBCentralManager(
            delegate: self,
            queue: .main,
            options: [
                CBCentralManagerOptionRestoreIdentifierKey: "it.unisalento.iotedgecompanionios.ble"
            ]
        )
    }

    func start(settings: EdgeSettings) {
        self.settings = settings
        self.mapping = BeaconMapping.parse(settings.beaconMapText)
        isMonitoring = true
        statusMessage = "Monitoraggio BLE in attesa del Bluetooth"

        if centralManager.state == .poweredOn {
            scheduleNextScan(after: 0)
        } else {
            bluetoothState = describeState(centralManager.state)
        }
    }

    func stop() {
        isMonitoring = false
        stopCurrentScan()
        scanTimer?.invalidate()
        nextScanTimer?.invalidate()
        scanTimer = nil
        nextScanTimer = nil
        observations.removeAll()
        discoveredObservations.removeAll()
        statusMessage = "Monitoraggio BLE fermato"
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        bluetoothState = describeState(central.state)

        if isMonitoring && central.state == .poweredOn {
            scheduleNextScan(after: 0)
        } else if central.state != .poweredOn {
            statusMessage = "Bluetooth non pronto: \(bluetoothState)"
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        willRestoreState dict: [String: Any]
    ) {
        statusMessage = "Stato BLE ripristinato da iOS"
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let identifier = peripheral.identifier.uuidString
        let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let name = peripheral.name ?? advertisedName ?? ""
        let rssi = RSSI.intValue
        let mappedRoom = mapping.room(for: identifier, name: name)

        let displayObservation = BeaconObservation(
            identifier: identifier,
            name: name,
            room: mappedRoom ?? "non_mappato",
            rssi: rssi,
            timestamp: Date()
        )
        discoveredObservations[identifier] = displayObservation
        updateRecentObservations()

        guard let mappedRoom else {
            return
        }

        let mappedObservation = BeaconObservation(
            identifier: identifier,
            name: name,
            room: mappedRoom,
            rssi: rssi,
            timestamp: Date()
        )
        observations[identifier] = mappedObservation
    }

    private func scheduleNextScan(after delay: TimeInterval) {
        guard isMonitoring else {
            return
        }

        nextScanTimer?.invalidate()
        nextScanTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            self?.startScanCycle()
        }
    }

    private func startScanCycle() {
        guard isMonitoring else {
            return
        }
        guard centralManager.state == .poweredOn else {
            statusMessage = "Bluetooth non pronto: \(describeState(centralManager.state))"
            scheduleNextScan(after: pauseBetweenScansSeconds)
            return
        }

        observations.removeAll()
        discoveredObservations.removeAll()
        isScanning = true
        statusMessage = "Scansione BLE in corso"
        centralManager.scanForPeripherals(
            withServices: nil,
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )

        scanTimer?.invalidate()
        scanTimer = Timer.scheduledTimer(withTimeInterval: scanDurationSeconds, repeats: false) { [weak self] _ in
            self?.finishScanCycle()
        }
    }

    private func finishScanCycle() {
        stopCurrentScan()

        guard let strongest = strongestObservation() else {
            statusMessage = "Nessun beacon mappato rilevato"
            scheduleNextScan(after: pauseBetweenScansSeconds)
            return
        }

        lastObservation = strongest
        statusMessage = "Stanza stimata: \(strongest.room)"
        Task {
            await sendObservation(strongest)
        }
        scheduleNextScan(after: pauseBetweenScansSeconds)
    }

    private func stopCurrentScan() {
        if isScanning {
            centralManager.stopScan()
        }
        isScanning = false
        scanTimer?.invalidate()
        scanTimer = nil
    }

    private func strongestObservation() -> BeaconObservation? {
        observations.values.max { first, second in
            first.rssi < second.rssi
        }
    }

    private func updateRecentObservations() {
        recentObservations = discoveredObservations.values.sorted { first, second in
            first.rssi > second.rssi
        }
    }

    private func sendObservation(_ observation: BeaconObservation) async {
        guard let settings else {
            return
        }

        do {
            let statusCode = try await EdgeReceiverClient.sendSample(
                settings: settings,
                observation: observation
            )
            await MainActor.run {
                statusMessage = "Inviata stanza \(observation.room) (\(statusCode))"
            }
        } catch {
            await MainActor.run {
                statusMessage = "Errore invio BLE: \(error.localizedDescription)"
            }
        }
    }

    private func describeState(_ state: CBManagerState) -> String {
        switch state {
        case .unknown:
            return "Sconosciuto"
        case .resetting:
            return "Reset Bluetooth"
        case .unsupported:
            return "Bluetooth non supportato"
        case .unauthorized:
            return "Permesso Bluetooth negato"
        case .poweredOff:
            return "Bluetooth spento"
        case .poweredOn:
            return "Bluetooth attivo"
        @unknown default:
            return "Stato Bluetooth non riconosciuto"
        }
    }
}
