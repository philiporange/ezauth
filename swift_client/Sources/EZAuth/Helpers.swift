import Foundation

extension String {
    /// Percent-encodes the string for safe use in a URL path segment.
    var urlPathEncoded: String {
        addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? self
    }
}
