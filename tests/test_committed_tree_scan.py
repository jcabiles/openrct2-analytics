import hashlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAX_WORD_RUN = 3
MIN_DECODED_FILES = 500
FORBIDDEN_DIGESTS = {
    "bca076af525287323b89eebe9b16f2a1a400219a05eeb07388d030c1ad90e1e9": "invented park ID",
    "c7da7aa9509ec6618e9e367d89dfbbb8cec3ff2aabf4cf3f9f869310b7a00ef3": "invented ride name",
    "1571a3e48fb6ded4cc2a2da7aaa75b9ad4abae6296d904dd3ca35b619a90fc63": "invented ride name",
    "5d906d9985113b1ed0ac915106141b349b8f98c56decf60ff12da1d9cfb8df90": "invented ride name",
    "60eece6f437185ec9d7ed79a73b360fa0f93be09625809999a560be2286bea05": "invented ride name",
    "dfe5fc4475c8c8f6857bb808fb33023e7525b9a17bc4017e7d3b981b67287f43": "invented ride name",
    "afeceacaadd1b4395019722181e6e86f1fff5247d9bb66fb2389585313f663ab": "invented ride name",
    "e1eb3fd8b6d1e77ca05a15d0c750e3cf38faa006659c9be8d6fa8371881de7c5": "invented ride name",
    "0dfa0f9725475e3becfc8f0f3ec91ad91992717ca26b08ce72a4f6274eec8431": "invented ride name",
    "4f7ce56e6ef44fb1482d339bce69696b49c5080723fe5d5aaf10d6d5c15bab1b": "invented ride name",
    "c425df7e5a6c210b6f9bcbb42bda5087d4598b182d171ffa6bd3bde0903f0fba": "invented ride name",
    "567534bb48041510b96516b2781d090e954b357d92daa5ede8979c7bff068f9c": "invented ride name",
    "65272d736368326b171392025c3fd9fb5bc2bc1460131e8557b3583ce4261921": "invented ride name",
    "a08dae75d1651d861b84f92c2f84625728cedc93588d8598be23bc637c485fe2": "test canary",
}
# Digests of the invented embedded data rows of the frozen mockup (trimmed, trailing comma
# removed). No row equals a value in the committed sample, so none is left out.
ROW_DIGESTS = {
    "89cd8c72d2fb57206d755d9c9ba580a105099de45c8a4f8d4e925270211cd70e",
    "f7480e722d06d8c55fde8e07f70048ddf54220e70464ed5989e2bb31e415609c",
    "7a63575ca29d3466c4a125b840ee2e8e41007934ab7a247e2efe6be48e601566",
    "5d0f4eca5c17f1de5d08e7a738f187282508d30c4e31b3f8482c6ed3cd18f9e3",
    "8f0af2527941ae5c350d9bcc842c637be9432a2bfa4ac48ec5231aa6b980776e",
    "34a406c56693061acd897a5725f7aa23d4b6d2d78234bc7cb68552c54e108f72",
    "b5863c4d95578d7e986eb5b31d9c418aacaade112c55c79f4dd0db0100aff6ee",
    "3891414288bada2eee8196eaf783e6c7eae066fe8550aa2e55fe20b09f9b2f06",
    "bca976fd466b2a016c4475751430ed16c2e65557c4e556e1147c573b22314134",
    "be36f01109bff762a56b5590cf0a440fd5fe2efefdd3ee2b2786853143548a77",
    "6bcadec112d15b59a33eb6e197af42b803eb39476e294a949f1b1a5afae0d3e3",
    "32d8bacbb8965442bbb6cd7659d8acd5010c575f810ce26dcaab719dde80ff6b",
    "178f1e3d083623bd264153328fc6537fb96105166f7bbea354eb1a0f267dcefb",
    "d31159789ff7d3518f4fc1132b3c78ddf707c6963b095e5d14b83d43084f6da1",
    "fc89017a3e5aa03f81edf8b0d783f21ada99e1f5d1eddf4c2dab99923507874f",
    "9715625866499c95f0b386f4c48714207a130a608548600567f45e2f9abaf121",
    "528bce23ff6b97071ddcee76062c39d4432492e805c1fe4632bf670b2db6c35e",
    "4e2a8d1c9574461b5fe7b28dbd41b21baf3dad52a34ad78861a25b96b1790dc0",
    "c4d014822652be9d74f25dc043d11dcda14b0c0d63e4be13603802bb4456d2a1",
    "9dd9d41e276a97fbad9f94bb930d0e7f99c8cd7fbf8d0632732606d98b657d5b",
    "1b222988264531b0c8205bf5d0766a9f7db94e276968b50fd587a89aab99cede",
    "b19ca1f59bd7056df9076e6a01180f90f34aaca7ce3f3a7244076ce9b951dca7",
    "93b66b902598737472f30ad3f644227af24ca1da7f2c43be5928e278b7c1746b",
    "a432396b9a222977881d42a9bae5d86ee76c4ecafccdbeb6586bf59c0434e7d6",
    "4caf0ae5160f48736d91def41306b0b07c27183d0f39de325afca2c816f8b55d",
    "43914de0125e279a8c4fdd1de6e753d9fd0a451a1400bbecc6234659859e50b6",
    "6f0e0e8cf1cc1d7a734a1a4dba466b0252706fda5085451f897ca62dccf1f157",
    "2d439f79eea8e7b4e1483ed85c28eb9f5fcf1f28a801e813430dfc0c753250fa",
    "a76fda9040978230328ceaa35e9a358fa76afea6650e5bb3c8354c5c10b72ada",
    "d2a67664b0436592d99cd9ef535396ad9d205cead7668882e7c4bde94142f34a",
    "f23cc2a8c81210931ec25019361b54bc894679b5dee5b5249189e0627903246f",
    "7281b439f1381151c851294a362889c19787a41d7fa1ab48c91439a3c6467c4f",
    "f90692c5cc5121042f5e517b6d5185ee8f8c52156fc1e2fadd76f8178dea7a3f",
    "e7f79067feb54aeb61ce7085c386980ed35ea2f1f9718f2f8cb903799c07ddba",
    "0d22acd2b0875eaf6cfa59e79d912416be85ffd5e951719342e198342d7aa66b",
    "7367d282ec6079b3200b1c27d2964221e70cc522ba4d4b9a96ae4f01ae3bf494",
    "b85500f3857271a87df9c212b513db496819febde8eb2d1e56460c3ff8d3454b",
    "f473961fda87dc19d55bbbda345a4435334ea20fa6ab1df0dd9f04388aff5d77",
    "51b816efd0573c93a434229fa40c36eeb0fc1d093f129f1d73b9197c99f40f7d",
    "b6480dcc9082d95aa60ff690b5095beef348b119e7c44a818e729a24ea0c7a8a",
    "5029337e88479e9ff0e0c48410ece72026250cd5a0d5a4d93b524bcad19872e5",
    "181e32848f228db0f9a176fe72063bed642e4ad392a392b43a15b4e3f10aeb73",
    "e00e0eb7f5f4eca2cbdb5e59824e96309d49730ea6bb10332243f4bb8712bcfe",
    "aae11ca23b8c57198247be4caa53bb2be4fd6d7d1d1c2b1a7e2f91cd96915f56",
    "42a9c606a7ed0c3faab0cf1546b0b0dc6ddb0ce5c5e1545023fb1e0403a3d7db",
    "3555441e68d07dd4c7a8c40017f2528747851065caea907735e61069d7eb3d8a",
    "618291ef2aab919d40f84fa2df87686cf130f42600b09aeafd681e6bdb59bef8",
    "487dc42e9c5bacbdf2c084a10298144b02492fe9e0f5977aac4b7d687eb52534",
    "6c80c63d596abf43849fa65479cc118ef1caeba79732391f6e31c39fa9a4aecc",
    "98b3240374b7aec67ede74a45efefa03898afb6e0e3933c3ee94ce60a5690243",
    "ce79ab180c506dfbb53068b0747c2c730682199fe780cfe804a0614908ac0b16",
    "5d9f1199a95268e28866e5d00eb668789068bd3b3eefbc645b8de677a6b87d83",
    "41fc63958e6efcf14396035332103a6890004d76a752ee2459d1614df5068ecb",
    "7491417b02eb2f59cff9eb72a6e4654e2f20eff2c8db828ffef7f01f1cb487b2",
    "5e78cb1894316cbd8898d1d0563c3f4c4805605e2f2fcffcec9632e77f2f60a4",
    "2a1a2e69fac34bc4edaf5dbd9893abe88c0f9e8c2dd7b47070624d286d9aa835",
    "4a027242ff3fe6475051ef0e138fef96b82a06781a6d5ef6f716f4f5b131e545",
    "7235d80e0df4965e14e5afa1e34ca4bd8b37c5b78f36f6841e1e9aeafe3ff1f9",
    "f9e332088b6b2b357d16c3610a0bc91f11c43d66ae8a1386477e08fe83d7c225",
    "1f8d5b959aea090dca8b13f7964b1014077dcc65a630ffc079e2943f2913bdbb",
    "0379c1a47ad7dcb8dda4347b86ff665d112a33f22c2177a33851abc488c6b073",
    "7096e2f287f05b8048dc1e2e5e967d6911f7d7364adff37304b436e0c1b46ba3",
    "fc7dc68d367b232f5797f0b95496639b663f205678deba8a3debe535f21d4a49",
    "3317912fefafe2f5078208bbc102a881adab9b218dc188f80ff5232f14445239",
    "5f5568db8326cd7143e0aeba3ae4cea868cc49a7f74c16f0906b04cd76b51123",
    "f7300764865ae3ceea7abd3595300a06206246dd45b21f9e27c455045a740c95",
    "f8e214c7fd1bdeff592bac4540ca3456f4685425e7e9cb6188afd3750efbe077",
    "d5c78f16a08981b8d4e9f86bb1f7e07c7d6b6325b3fcdacc3cf1e26936b92222",
    "ae5a3f7556632f87b4724bad98e5fecef84168866bb00d8d61815d88927f63ff",
    "abee3ebfb2a7ad805424ac03d0c6f7cede027d41cbf5567e85bdf5fd2ee11730",
    "ef4be57f37a902c2cbd0eb07ba4230bd422ed5c1758371b24d5c4eb08ef37c4a",
    "21f74699bd8fb0438ec8fa2300b51d6f114932767c33493a370f50d1484c115e",
    "6ea4ba21f82a9db67fb2837b68c8f21ab5769b9585910196354c12b11e7ec8de",
    "5f88e8be16d6dc2a5afa76fb74e8581b088e9643bf09f727154cdba09706ad69",
    "f4e1c1afd220d5aa1c44153a4af270e16abd1d06e52bf5b08fc562357052bd54",
    "4c578440984da5ca0b49d840d68d8d5434fd7eb8c9bc875ba070c002febf59d8",
    "a1f85bec9517f3dda891b8c7c8a7620e7889bc5e803642834d69a4074adbbee4",
    "33ac21b277ec85a0d020effe0ed6eb8dc83abf7fde146792a7cf44b4e221169a",
    "db612a7a7313e5f02b87691478865376cfec4ccac7656f4172fa259967f2e930",
    "11de17505ebcc7eb96059b5f52ab9e8e6ca3af402d4442919b2c39db627ae6b7",
    "d256951f314acf816bd564f6e7f96aa203bbd8636a832851af657eb1fdd3b367",
    "fda0e1ec7fe67fab20f52b8344f3b4eec5e15f19dbe3a15a65383cce27c7be89",
    "96bb7c8d5060039bfce0897882d1f0cf9956b560b1a001d2daf167e9d7652282",
    "a15bc1e7e2601dbe6403c7f038c3e139ed386140fea5caeeed8027ab3011df09",
    "f9c16a11cc5593b851aac8d7f252603ca2121f01ffe9d1551f6090c2d63fe1db",
    "d09e57111f769540dba8be8829e2a84e41cc5326849357ee19bbb891a5978e34",
    "fa986855ea8e484eb42d4bd402ddc519e32a9b1ca9defa8a199bb767adf065d9",
    "3db73e1939dfb6045b6a1659ac809f95661cb945e35dedfdb3a3bc1360e8e3f3",
    "aaf3328dbb8db11d36d58eeeefe6edec9c0bc7000cac5ec8011fa98975254205",
    "972a429b041adedef84a7c5e3403aa572ab4a3be16bc2e40a8f49e49be48ddc2",
    "7fba541611a4441aa39977dd5dcae9832666a429c569158598b4d23efbd5678a",
    "4996144a72bcd4cbb4a4293bd5321ad9ace88263eed02a5155c1067914afc68b",
    "0c3f557b334b0e41f324cf7e7fcb3de4797cc0ec547be3b23dc053a675fc575a",
    "2e870f080ae44a3c805392b46572a266022c7938ff37bc5aede4356409e607d3",
    "98daf47df87923875c993a20a94aa5e69f2f01cc44115a05eec1d4ce91bd9cf6",
    "dbe5fac47643c9235cd799a8c3e3716c2cdead9d57cef132947645c834981b55",
    "8c2fbc7ddaee1b6c8bb7cb97b9047c1b13f9233fb41c7cb763615ea952f9a04e",
    "d936478bd1f610ad83333acdfca6fdfe036b9347fea6419aac4d402ac18290ad",
    "908e3550b07ceb42b0be5b2881cc7f8459ce60cab458f310025e7f29666b975b",
    "bfe69c4e4b42236eef5b1315332be38bd883e6939b8c661b2b9b2e7af0045202",
    "4b68b8d1f85efdc9f8ddd8c671c5116d9f6dc23aadcdf45c4aad4e422c85bd11",
    "0e7897817b45ab97ca3de7db7165730ec77bec29e74c04326967f704ed809017",
    "ae4ff6e0d9b7aaea8dad7cc32f28395bfcc63773a5e0a0069a02094da806e802",
    "c5095eee96ac3dbfda0e6e50fef1553ab39b48b527767f39db0d81865e89ff2f",
    "4345af061c260f3fcf55c80b5714c6ecc750cb44b3edad8dd0ca6552247532db",
    "ddca7a943c6b42758f659f5ee11db368a77a137d5340dde87af0a552799a10db",
    "5b7c333a7c72db41c81aea0db441058e124a29b8e61b74a968ca0f346bcf4104",
    "c6f142bc1071bc7bf1921c0214ab5bd93ed51b05e72a5331b91d229c43c1529d",
    "4b4016d9c2670ceec9a54aa2291153f024743458fe0ad9ec569f8c3687a1463b",
    "9f6c4af74e69344079147737101cfacfc2bd06e898b42e6bc5c331a8dafaba43",
    "7f6f4630f5fd7fd8394e124690deee9092af26245ef2aa43c58cb61e7580c80f",
    "5cdad772a01260f7d747b51d9ec1234feeec62e0a0a467a845e990a14cea1742",
    "6fb1b46ae2a42dfb1959f908191813a73e5e856d876a85c0d62da9b9e0c8f375",
    "d163afcb6392c7de72ae6d5f238583d7e9b5799ef2bceae0b61bdf97a00dc3d3",
    "c6ab0aa3ac9995f2d829fd7a0fc24d4afe3ac3299299583ae004e6652388df2f",
    "1b1d8f87ddf587df372a1e81a1fba8ca4eeb0972feb322ab9baecb3c9224276b",
    "c485e56ef9045230b600c52b6e50aa7f43e4aa8e67e2b7d83480cab4f1343ba9",
    "091b6acb9a5dbb9373e5e5d76f2fcfd0251bdc37901a0884c21deaccc4e962b7",
    "980cb15032e2dba2d8d30eba5e2f67ea5a8b5197f8cf182ca07c86aa5d5e1eea",
    "8ceece132180f3e41c87fba63f8bb887853d2b30e9cdb2dd438fe457296abc4b",
    "53d2c874954993537acc399dad906aeeb34683713873e01919bf06050e915afe",
    "b912c5cb28b68444964cda363e8ea514aacb74306122158ba5b82a8906f066ca",
    "14ae460adfa6bff4e9d4aed26a2e3e94b7b3ac39e879f4dee68538ad77d43438",
    "cec7f98af934f7a4a7b0f18c803c527c075407c2645b1de7370730782f3c9c33",
    "bdaacdb486937e72d360c6ca06efe2d4a8de7dd09862727459d5e4c63097420a",
    "9d7e25713a33bcb7b8bbabbd667bea908bcaa4bc82961580182e9f9b69eeb93f",
    "4f451e7d6f3445816903013462a769c1ad4fb49a418885e6542a8a41436c10fe",
    "ce3279b7e1282f57913d33a2aa2087483bc74200e5cda4e9a2aebd9816ef4ada",
    "ed4e406031ade4f0af7c0f3171abd2daec698832921cef3c22c363aeaba2f49e",
    "8cd21c1f7c4673cbb7529a41795abd24c343b94bd0b20db60de8efc342b48644",
    "6ee93a23cc535570a61a54630d2017128659a2faaabb1fa3ef145e5cdde50432",
    "d00cf0cada3d8b2ab5d9b599a6ff51ac9458fa5b01bc6ffb71bf8c0123b72d71",
    "a18e7050b142945842268223dd0c37e71ba9639c6c9e1d4b8edff3429cc945d8",
    "8280458bf106a5218be73ccb2f7c0bd4bf9683e0ed682ab921aefd03a876d1bc",
    "d630bc6ebbe9012f0851b8381c726b8953ac9e97b8db0280d1056b741fa5926c",
    "f4b0f75bd47dc6f471f3c0acbd3a1c2eb850d6b54b6ea570071bd303945bb978",
    "4f980b4718ce5fd56a6241edeed37b2dcc98b8fe7d9158a765c498683634a21a",
    "0d6eeb35a56d7b982f32ed48ba59905fe04580c3af4cd8a8dd6e368c1f0549c4",
    "f98261c513d473efec925911f4e993527a37ddbc1a3381d9dc08bc1d1d5b4206",
    "12cb9e633237788795838eeb1f306e481fd6750df21b29e4b805779633912864",
    "ae77b0447878e63f4d7b2b557b158199ede93f76435dfe11d5c7995f8f4c39fc",
    "88dfc8e3a700bbdad4752396020bc4559979b68bfc5afc7b39030d34a6927102",
    "c5f727fd11c8022b18d4bd66d6906b747aae4e94df075218a2ed8d13ca4332e4",
    "2b4260305706124650401a207bcd19919607005f4d135afc02aa1ebc47b2c693",
    "0ab99c4f318c46776eecf5be3900b80f3e56622709b2f99eb8f1eff41f96321b",
    "bb6a0684b2094c4ef0813f0dfd198ed0260f811a0aa6e8edaf5e978010d72583",
    "31726d22f203be35c02546e711c111e240575f1236729bf20c6491b6aaa98c14",
    "51820293e7c8a2b6884b828efbb0da58903dc8a9b53368d7de0acd8767a76f2a",
    "ec93c1c197da9dd6fbbddcd92d4a444528ce03c921bcbee84e4bb109f011ffe7",
    "c4cb3a116d5529b7de7dfd1e84fcca610280c3b8b7c7c0ab31a28b215fad21dc",
    "1918750a04c5e0c86abf8002c78422c73dcfa857691befdec6181cb1d5d89446",
    "400931eff4209dfda3780ca84e63fd4a2d2840bda7ba504a410800d7de7b6a72",
    "8a2ec2e2aaa392da53948dfed5d09062cda39a705237ee2ff8357aefaa317a63",
    "091a2efbe4d2cf9c8062055d1f320dd306708aa54d1552be6d7a58dd9b7b4329",
    "7aac2f2c39c6a797ba5efb6a0de04cbd80cf77d94ea17db0ecac7830f7744334",
    "5e3a79806eac63c2fea6a6cb94b3dbd17e17118b57c35ad6b7e80bce5501e646",
    "4ce96f97ac9db2a5316ff0501cf11977623f75988460ce0e684eaf2a4ed854b6",
    "8a62d26566f53e0fa152952905ae2b944ee0be8987d427073521f68e871a3c0b",
    "92e427846b75b2211b69544d2bb6bcc79fc9b3433f32020ef43bb48c2d64c12f",
    "1ffec5aa9070f0825189e4a939ead637c8fefec5441236c70c4c91bcbedff1c5",
    "5ba0d9fdf7385ac866ff023a48095e643f78cc53911c2d35619505b4185993ab",
    "1a8343eb0f9bdefc53cd4ac062ab9538207549f4ef3ba8ad20b8b807ed24b33e",
    "a96748ee767d87b4051150efbf06dd5edf5ca4c7ff5ca2c598ea36238cd2a981",
    "ddb4997520adc60a9d5c4ac5de30a01cb97d2047de43fba454cb57ce1f94ab9d",
    "34cdbea839e90134d261e39088e662640cc68eec62dc97a47ec848f176714d94",
    "17f0c7757166805d048195a58dfd77bd9d456fb13bffa331da322a038a278b45",
    "e406a07973107527aad0f768a0ac19a725a2697fe08cacbc2bf82c5a1e892d55",
    "5dd2e7bb0faff6de497ac076fce2f71f9a6c880544cc05af4f103ca2c2633cce",
    "71f2cefb817e9ab254e9d839110409ce9335d60894ecc491379535dab5027e77",
    "1bfebc2a044e2df31d055287fc762eea181324ff51464ce686b6679584352214",
    "08998f6607176d395159fb26bc75e396e7574b6ba98ed7b97c64139327baa60f",
    "29893dbca946de224ada42ae36ba76a0fb0b6ce9c8e974b7df1562939b9f7ad9",
    "c4c11667b2080b635dd2633554161a98d60633f78787dfa8b5c409908b903310",
    "cad3ec2b6546cff5aabe8ea4c3982f55e0d1bc96996bc879ea5e7f8a1d4fdcc6",
    "2ef3349aa7ba4300bf01eef3f8ed831de8662187c32003ee884357c6d7fd8dbc",
    "d2bd07b19085f0aaa84ad2814a991fb12cf1f6eb80706989446cb833d741be74",
    "be698292557f262808bb0773e8db94f15efbdf01b7b95f080b36f1afd0197b06",
    "6bcc960b199e9997ffe9a80e6da20cd4f41f46fd7006cb130d31e6b9eabaa853",
    "cf62035f0650a87bb85d9b2a4ebf633fc35c733b214aef6f61858990a5dd7193",
    "126cfb0ec245e969a82ba1f2451279618187b5f881cee558c97f4bf934650c3b",
    "b454367889c3f2df84500edf765c83d474ebe7f6d6197e92da27e2f558e0833e",
    "0820e65163e6b3fe78d52f0c9e442da53bdaa7f03f477870304d76a9fb87ec95",
    "2724a518f039087b14f3bc5d8e2f72fe01d41f1c9531fa4774218e56a8635a76",
    "a23d01ff85652637d94d891e944da11e1834328de92c6c30d55f8f7d60672af2",
    "8b5d1da1fdfcd402645c9febc85234c75b9568987dc4d5f04b9f42591bf4eb66",
    "18d55d33ec5d419d7a4290ff4903493d83468720a1dae8de5a1db16021266770",
    "713ffe78cb7cda6227ab990da53a41ead234f4f3122f4406152b219f2972ea7c",
    "2671241819194d70d28615c223a30a8dc698066dcd2c1de67f6c81c3b268c90e",
    "dcb07899472e99473a47a614696a3abe701427495f1d078bccc91bca7de53aa2",
    "dccca4a44044f65c3e6db102b6cf5f7ae2d1c6a106b2c5a66441aed1762e65c1",
    "db9eb475026cb3a5365380401a349a304f4254efe3c1838201bfb7a85009a3e6",
    "98463f467789df85b38d8ae8b6ca4c6aeb51dd2312dc0dbcdab1b622928718b5",
    "445d6d5e03704f4791f23bd75a1455351d24f3065f2c6ab06e3f13fd62e01364",
    "49853df503be29afdaf367249b7a24a1566ae00b2466442b5ddf572f06b1f9f4",
    "b610044516e93a6b456d5a1535d45618b7be8f25e0ee445ad2bede3de67e30c8",
    "e2388283b0a24908ce68152008cb5660c255d5abf836de48636de469a002980b",
}
WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _candidates(line: str) -> set[str]:
    words = WORD_RE.findall(line)
    candidates = {line.strip().removesuffix(",")}
    for identifier in IDENTIFIER_RE.findall(line):
        parts = identifier.split("-")
        for start in range(len(parts)):
            for end in range(start + 1, len(parts) + 1):
                candidates.add("-".join(parts[start:end]))
    for start in range(len(words)):
        for size in range(1, min(MAX_WORD_RUN, len(words) - start) + 1):
            candidates.add(" ".join(words[start : start + size]))
    return candidates


def _decoded(files: list[tuple[str, Path]]) -> list[tuple[str, str]]:
    decoded = []
    for display_path, path in files:
        data = path.read_bytes()
        if b"\0" in data:  # binary file (parquet, images): not text, nothing to scan
            continue
        decoded.append((display_path, data.decode("utf-8")))
    return decoded


def _scan(files: list[tuple[str, Path]]) -> list[tuple[str, int, str]]:
    matches = []
    for display_path, content in _decoded(files):
        for line_number, line in enumerate(content.splitlines(), start=1):
            for candidate in _candidates(line):
                digest = _digest(candidate)
                if digest in FORBIDDEN_DIGESTS or digest in ROW_DIGESTS:
                    matches.append((display_path, line_number, digest))
    return matches


def _tracked_files() -> list[tuple[str, Path]]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [(name, ROOT / name) for name in result.stdout.decode("utf-8").split("\0") if name]


def test_tracked_listing_holds_known_files_and_decodes_many() -> None:
    files = _tracked_files()
    names = {name for name, _path in files}
    assert "docs/ai-dlc/contracts/site-mockup-port.md" in names
    assert "tests/test_committed_tree_scan.py" in names
    assert len(_decoded(files)) > MIN_DECODED_FILES


def test_tracked_text_files_contain_no_invented_values() -> None:
    matches = _scan(_tracked_files())
    assert not matches, "forbidden values found:\n" + "\n".join(
        f"{path}:{line}" for path, line, _digest_value in matches
    )


def test_canary_is_reported_from_a_temporary_docs_copy(tmp_path: Path) -> None:
    tracked_path = ROOT / "docs/ai-dlc/contracts/site-mockup-port.md"
    copy_path = tmp_path / "docs/ai-dlc/contracts/site-mockup-port.md"
    copy_path.parent.mkdir(parents=True)
    copy_path.write_bytes(tracked_path.read_bytes())
    canary = " ".join(reversed(("marigold", "cypress", "semaphore")))
    with copy_path.open("a", encoding="utf-8") as planted:
        planted.write("\n" + canary + "\n")

    matches = _scan([("docs/ai-dlc/contracts/site-mockup-port.md", copy_path)])
    assert matches == [
        (
            "docs/ai-dlc/contracts/site-mockup-port.md",
            len(tracked_path.read_text(encoding="utf-8").splitlines()) + 2,
            "a08dae75d1651d861b84f92c2f84625728cedc93588d8598be23bc637c485fe2",
        )
    ]


def _planted(tmp_path: Path, text: str, name: str = "planted.md") -> list[tuple[str, Path]]:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return [(name, path)]


def test_hyphenated_canary_is_reported_through_the_identifier_path(tmp_path: Path) -> None:
    canary = "-".join(reversed(("2", "park", "illustrative")))
    matches = _scan(_planted(tmp_path, f"see {canary} here\n"))
    assert [(path, line) for path, line, _digest_value in matches] == [("planted.md", 1)]


def test_sub_chain_inside_a_longer_hyphen_chain_is_reported(tmp_path: Path) -> None:
    canary = "-".join(reversed(("row", "2", "park", "illustrative")))
    matches = _scan(_planted(tmp_path, f"{canary}\n"))
    assert [(path, line) for path, line, _digest_value in matches] == [("planted.md", 1)]


def test_embedded_data_row_is_reported_with_its_trailing_comma(tmp_path: Path) -> None:
    row = "[" + ", ".join(('"ride-05"', '"2000-07-01"', "98", "259")) + "]"
    matches = _scan(_planted(tmp_path, f"      {row},\n"))
    assert [(path, line) for path, line, _digest_value in matches] == [("planted.md", 1)]


def test_file_with_a_nul_byte_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "binary.bin"
    path.write_bytes(b"\xff\x00\xfe")
    assert _decoded([("binary.bin", path)]) == []


def test_non_utf8_text_file_is_not_skipped_silently(tmp_path: Path) -> None:
    path = tmp_path / "latin1.txt"
    path.write_bytes(b"caf\xe9\n")
    with pytest.raises(UnicodeDecodeError):
        _decoded([("latin1.txt", path)])
