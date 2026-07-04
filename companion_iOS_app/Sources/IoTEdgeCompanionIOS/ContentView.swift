import SwiftUI

struct ContentView: View {
    @StateObject private var bleMonitor = BleMonitor()

    @AppStorage("receiverURL")
    private var receiverURL = "http://192.168.1.10:8000/ble/sample"

    @AppStorage("phoneID")
    private var phoneID = "iphone-emili"

    @AppStorage("beaconMapText")
    private var beaconMapText = """
    BeaconCucina=kitchen
    BeaconCamera=bedroom
    BeaconBagno=bathroom
    BeaconSoggiorno=living_room
    """

    @AppStorage("manualRoom")
    private var manualRoom = "kitchen"

    @AppStorage("manualRSSI")
    private var manualRSSI = "-61"

    @AppStorage("manualBeaconID")
    private var manualBeaconID = "manual-beacon"

    @State private var manualStatus = "Pronto"

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("IoT Edge Companion")
                            .font(.title2)
                            .fontWeight(.semibold)
                        Text("iOS")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                }

                Section("Gateway Raspberry") {
                    TextField("Receiver URL", text: $receiverURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)

                    TextField("Phone ID", text: $phoneID)
                        .textInputAutocapitalization(.never)
                }

                Section("Mappa beacon / stanza") {
                    TextEditor(text: $beaconMapText)
                        .font(.system(.body, design: .monospaced))
                        .frame(minHeight: 120)

                    Text("Formato: identificativo_o_nome=stanza")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Campione manuale") {
                    TextField("Room", text: $manualRoom)
                        .textInputAutocapitalization(.never)

                    TextField("RSSI", text: $manualRSSI)
                        .keyboardType(.numbersAndPunctuation)

                    TextField("Beacon ID", text: $manualBeaconID)
                        .textInputAutocapitalization(.never)

                    Button {
                        sendManualSample()
                    } label: {
                        Label("Invia manuale", systemImage: "paperplane.fill")
                    }

                    Text(manualStatus)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Monitoraggio BLE") {
                    HStack {
                        Label(bleMonitor.bluetoothState, systemImage: "dot.radiowaves.left.and.right")
                        Spacer()
                        if bleMonitor.isScanning {
                            ProgressView()
                        }
                    }

                    Button {
                        bleMonitor.start(settings: currentSettings)
                    } label: {
                        Label("Avvia monitoraggio BLE", systemImage: "play.fill")
                    }
                    .disabled(bleMonitor.isMonitoring)

                    Button(role: .destructive) {
                        bleMonitor.stop()
                    } label: {
                        Label("Ferma monitoraggio BLE", systemImage: "stop.fill")
                    }
                    .disabled(!bleMonitor.isMonitoring)

                    Text(bleMonitor.statusMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let observation = bleMonitor.lastObservation {
                    Section("Ultima stanza inviata") {
                        ObservationRow(observation: observation)
                    }
                }

                Section("Beacon rilevati") {
                    if bleMonitor.recentObservations.isEmpty {
                        Text("Nessun beacon rilevato nell'ultima scansione")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(bleMonitor.recentObservations) { observation in
                            ObservationRow(observation: observation)
                        }
                    }
                }
            }
            .navigationTitle("Companion")
        }
    }

    private var currentSettings: EdgeSettings {
        EdgeSettings(
            receiverURL: receiverURL.trimmingCharacters(in: .whitespacesAndNewlines),
            phoneID: phoneID.trimmingCharacters(in: .whitespacesAndNewlines),
            beaconMapText: beaconMapText
        )
    }

    private func sendManualSample() {
        let observation = BeaconObservation(
            identifier: manualBeaconID.trimmingCharacters(in: .whitespacesAndNewlines),
            name: "ManualBeacon",
            room: manualRoom.trimmingCharacters(in: .whitespacesAndNewlines),
            rssi: Int(manualRSSI.trimmingCharacters(in: .whitespacesAndNewlines)) ?? -70,
            timestamp: Date()
        )

        manualStatus = "Invio campione..."
        Task {
            do {
                let statusCode = try await EdgeReceiverClient.sendSample(
                    settings: currentSettings,
                    observation: observation
                )
                await MainActor.run {
                    manualStatus = "Inviato \(observation.room) (\(statusCode))"
                }
            } catch {
                await MainActor.run {
                    manualStatus = "Errore invio: \(error.localizedDescription)"
                }
            }
        }
    }
}

private struct ObservationRow: View {
    let observation: BeaconObservation

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(observation.room)
                    .font(.headline)
                Spacer()
                Text("\(observation.rssi) dBm")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if !observation.name.isEmpty {
                Text(observation.name)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }

            Text(observation.identifier)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
