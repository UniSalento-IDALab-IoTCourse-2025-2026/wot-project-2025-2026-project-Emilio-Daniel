import Foundation

enum EdgeReceiverError: LocalizedError {
    case invalidURL
    case invalidResponse
    case httpError(Int)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Receiver URL non valido"
        case .invalidResponse:
            return "Risposta receiver non valida"
        case .httpError(let statusCode):
            return "Receiver HTTP \(statusCode)"
        }
    }
}

struct EdgeBleSamplePayload: Encodable {
    let timestamp: String
    let room: String
    let rssi: Int
    let beacon_id: String
    let beacon_name: String
    let phone_id: String
}

enum EdgeReceiverClient {
    static func sendSample(
        settings: EdgeSettings,
        observation: BeaconObservation
    ) async throws -> Int {
        guard let url = URL(string: settings.receiverURL) else {
            throw EdgeReceiverError.invalidURL
        }

        let payload = EdgeBleSamplePayload(
            timestamp: ISO8601DateFormatter().string(from: observation.timestamp),
            room: observation.room,
            rssi: observation.rssi,
            beacon_id: observation.identifier,
            beacon_name: observation.name,
            phone_id: settings.phoneID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "iphone"
                : settings.phoneID
        )

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)

        let (_, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw EdgeReceiverError.invalidResponse
        }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw EdgeReceiverError.httpError(httpResponse.statusCode)
        }
        return httpResponse.statusCode
    }
}

