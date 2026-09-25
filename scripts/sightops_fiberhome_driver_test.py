from __future__ import annotations

import unittest

from app.cli.tools.olt_fiberhome import (
    parse_discovery,
    parse_distance,
    parse_fdb,
    parse_global_vlan_services,
    parse_authorization,
    parse_layout,
    parse_last_on_off,
    parse_macs,
    parse_online,
    parse_pon_macs,
    parse_signal,
    parse_states,
    parse_versions,
    fiberhome_onu_type,
)


class FiberHomeDriverParserTest(unittest.TestCase):
    def test_layout(self) -> None:
        layout = parse_layout(" 4 up connected GC8B\n 10 up connected SMU_master")
        self.assertEqual(layout.slots, (4,))
        self.assertEqual(fiberhome_onu_type("AN5506-01-A1"), "5506-01-A1")
        self.assertEqual(fiberhome_onu_type("HG260"), "HG260")

    def test_online_and_versions(self) -> None:
        online = parse_online(
            "05 AN5506-01-B1 FHTT927025d8 ,\n"
            "--Press any key to continue-- Master 35 HG260 TPLGe7bda090 ,",
            4,
            1,
        )
        self.assertEqual([row["onu_id"] for row in online], [5, 35])
        self.assertEqual(online[0]["onu_serial"], "FHTT927025D8")
        versions = parse_versions("05 AN5506-01-B1 AN5506-01-B1 RP2604 WKE2\n")
        self.assertEqual(versions[5], "AN5506-01-B1")
        authorized = parse_authorization(
            "4 1 5 AN5506-01-B1 A FHTT927025d8 ,\n"
            "--Press any key-- Master 4 1 31 HG260 A HWTCfa9e92ae ,"
        )
        self.assertEqual([row["onu_id"] for row in authorized], [5, 31])
        self.assertEqual(parse_states("onu 5 is active.\nonu 31 is inactive."), {5: "Active", 31: "Inactive"})

    def test_authorization_preserves_native_serial_case(self) -> None:
        """Regressao do bug real: excluir PON1/ONU31 (HG260) falhava na OLT
        com "sn is wrong!" porque o comando de delete usava o serial em
        upper (HWTCFA9E92AE) enquanto a whitelist da FiberHome, case-
        sensitive, tem o serial gravado como a OLT devolveu (HWTCfa9e92ae).

        onu_serial continua em upper (usado em todo o sistema pra
        comparacao/exibicao/historico); onu_serial_raw preserva a caixa
        exata da OLT e e o que delete_onu_fiberhome usa pra montar o
        comando de exclusao.
        """
        authorized = parse_authorization(
            "4 1 5 AN5506-01-B1 A FHTT927025d8 ,\n"
            "--Press any key-- Master 4 1 31 HG260 A HWTCfa9e92ae ,"
        )
        onu31 = next(row for row in authorized if row["onu_id"] == 31)
        self.assertEqual(onu31["onu_serial"], "HWTCFA9E92AE")
        self.assertEqual(onu31["onu_serial_raw"], "HWTCfa9e92ae")

    def test_signal_distance_and_macs(self) -> None:
        signal = parse_signal(
            "SEND POWER : 2.69 (Dbm)\n"
            "RECV POWER : -24.31 (Dbm)\n"
            "OLT RECV POWER : -20.10 (Dbm)"
        )
        self.assertEqual(signal["onu_rx"], "-24.31")
        self.assertEqual(signal["olt_rx"], "-20.10")
        self.assertEqual(parse_distance("ONU RTT VALUE = 1546 (m)"), "1.546")
        self.assertEqual(
            parse_last_on_off(
                "Last Off Time = 2026-06-01 10:20:30!\n"
                "Last On Time = 2026-05-02 09:08:07!"
            ),
            {"last_off_at": "2026-06-01 10:20:30", "last_on_at": "2026-05-02 09:08:07"},
        )
        self.assertEqual(
            parse_last_on_off(
                "Last Off Time = 0000-00-00 00:00:00!\n"
                "Last On Time = 0000-00-00 00:00:00!"
            ),
            {"last_off_at": "", "last_on_at": ""},
        )
        macs = parse_macs(
            "001 14:22:33:70:25:D8 Vid:65535\n"
            "002 18:E8:29:2C:43:F2 Vid:640\n"
        )
        self.assertEqual(macs[0]["vlan"], "")
        self.assertEqual(macs[0]["vlan_mode"], "untagged")
        self.assertEqual(
            macs[1],
            {
                "cpe_mac": "18:e8:29:2c:43:f2",
                "vlan": "640",
                "vlan_mode": "tagged",
            },
        )

    def test_fdb(self) -> None:
        parsed = parse_fdb(
            "Mac: 0c:83:9a:70:ae:a5   Vid: 500\n"
            "Mac: 18:E8:29:2C:43:F2   Vid: 640\n"
        )
        self.assertEqual(parsed["0c:83:9a:70:ae:a5"], "500")
        self.assertEqual(parsed["18:e8:29:2c:43:f2"], "640")

    def test_pon_macs(self) -> None:
        parsed = parse_pon_macs(
            "001 00:1A:3F:05:52:7B Vid:600 OnuId:10\n"
            "002 0C:83:9A:70:AE:A5 Vid:500 OnuId:7\n"
            "003 22:3E:44:55:66:11 Vid:4091 OnuId:65535\n"
        )
        self.assertEqual(
            parsed,
            [
                {
                    "cpe_mac": "00:1a:3f:05:52:7b",
                    "vlan": "600",
                    "onu_id": 10,
                    "vlan_mode": "mapped",
                    "vlan_source": "pon_mac",
                },
                {
                    "cpe_mac": "0c:83:9a:70:ae:a5",
                    "vlan": "500",
                    "onu_id": 7,
                    "vlan_mode": "mapped",
                    "vlan_source": "pon_mac",
                },
            ],
        )

    def test_discovery_preserves_native_serial_case(self) -> None:
        """Regressao do bug real: autorizar a ONU descoberta HWTC746ebb4c
        falhava com "[ERR -598] physical address is error!" porque
        add_onu_fiberhome mandava o serial em upper (HWTC746EBB4C) no
        comando de whitelist -- a mesma causa-raiz do bug de exclusao
        (test_authorization_preserves_native_serial_case), so que na
        descoberta (show unauth_discovery) em vez da autorizacao.

        "serial" continua em upper (exibicao/comparacao); "serial_raw"
        preserva a caixa exata que a OLT devolveu e e o que
        add_onu_fiberhome deve usar pra montar o comando de autorizacao.
        """
        parsed = parse_discovery(
            "----- ONU Unauth Table ,SLOT=4 PON=3 ,ITEM=1-----\n"
            "1     HG260    HWTC746ebb4c ,"
        )
        entry = parsed["3"]["discovered"][0]
        self.assertEqual(entry["serial"], "HWTC746EBB4C")
        self.assertEqual(entry["serial_raw"], "HWTC746ebb4c")

    def test_empty_discovery_keeps_pons(self) -> None:
        parsed = parse_discovery(
            "----- ONU Unauth Table ,SLOT=4 PON=1 ,ITEM=0-----\n"
            "----- ONU Unauth Table ,SLOT=4 PON=2 ,ITEM=0-----"
        )
        self.assertEqual(set(parsed), {"1", "2"})
        self.assertEqual(parsed["1"]["discovered"], [])

    def test_global_vlan_services(self) -> None:
        parsed = parse_global_vlan_services(
            "***********************************************\n"
            "service name   : OOPS\nbegin vid : 1125\nend vid : 1125\nservice type : data\n"
            "***********************************************\n"
            "service name : OOPS_TV\nbegin vid : 1334\nend vid : 1334\nservice type : iptv\n"
        )
        self.assertEqual(parsed[1125], {"name": "OOPS", "type": "data"})
        self.assertEqual(parsed[1334], {"name": "OOPS_TV", "type": "iptv"})


if __name__ == "__main__":
    unittest.main()
