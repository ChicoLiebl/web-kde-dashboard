import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    property alias cfg_url: url.text

    Kirigami.FormLayout {
        QQC2.TextField {
            id: url
            Kirigami.FormData.label: i18n("kddash address:")
            placeholderText: "http://127.0.0.1:8765"
        }
        QQC2.Label {
            text: i18n("The access token is read from ~/.config/kddash/token.")
            opacity: 0.7
        }
    }
}
