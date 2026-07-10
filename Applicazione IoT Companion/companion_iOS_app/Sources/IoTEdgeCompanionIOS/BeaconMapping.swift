import Foundation

struct BeaconObservation: Identifiable, Equatable {
    let identifier: String
    let name: String
    let room: String
    let rssi: Int
    let timestamp: Date

    var id: String {
        identifier
    }
}

struct BeaconMapping {
    private let values: [String: String]

    static func parse(_ text: String) -> BeaconMapping {
        var parsed: [String: String] = [:]

        for line in text.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty || !trimmed.contains("=") {
                continue
            }

            let parts = trimmed.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else {
                continue
            }

            let key = normalize(String(parts[0]))
            let room = normalize(String(parts[1]))
            if !key.isEmpty && !room.isEmpty {
                parsed[key] = room
            }
        }

        return BeaconMapping(values: parsed)
    }

    func room(for identifier: String, name: String) -> String? {
        let normalizedIdentifier = Self.normalize(identifier)
        if let room = values[normalizedIdentifier] {
            return room
        }

        let normalizedName = Self.normalize(name)
        if let room = values[normalizedName] {
            return room
        }

        for (key, room) in values {
            if !key.isEmpty && normalizedName.contains(key) {
                return room
            }
        }

        return nil
    }

    private static func normalize(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}

